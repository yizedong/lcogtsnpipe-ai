"""Stage ``wcs``: verify (and if needed re-fit) the astrometric solution.

The old pipeline trusts BANZAI's solution (WCSERR=0, photlco.wcs=0) and only runs ``lscastro`` when
BANZAI failed; checking it needed a human (``checkwcs`` overlay in ds9). Here every frame is measured:
sep detections are matched to the Gaia catalog of the target and the median offset, robust scatter and
number of matches are recorded (what the human judged by eye). Frames with WCSERR != 0 or a failed
check get a new TAN solution fitted to the matches (``astropy.wcs.utils.fit_wcs_from_points``, the
equivalent of the old ``ccmap`` linear fit). DB ``wcs`` = 0 good / 9999 failed, quality=1 on failure,
as before.
"""
import time
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from . import catalogs, config, db
from .qa import FrameQA

# rms limit as the old lscastro (quality=1 when rms > 2"); the offset limit is a warning only
GATES = dict(min_matches=10, max_rms_arcsec=2.0, max_offset_arcsec=1.0)


def detect(data, thresh=5., minarea=5):
    import sep
    d = np.ascontiguousarray(data, dtype=float)
    bkg = sep.Background(d)
    obj = sep.extract(d - bkg.back(), thresh, err=bkg.globalrms, minarea=minarea)
    return obj[(obj['flag'] == 0)]


def measure(data, hdr, cat, radius=2.):
    w = WCS(hdr)
    obj = detect(data)
    if len(obj) == 0:
        return None
    sky = w.pixel_to_world(obj['x'], obj['y'])
    c = SkyCoord(np.asarray(cat['ra'], float), np.asarray(cat['dec'], float), unit='deg')
    idx, sep2d, _ = sky.match_to_catalog_sky(c)
    m = sep2d.arcsec < radius
    if m.sum() == 0:
        return dict(n_match=0, obj=obj, idx=idx, m=m, cat=c)
    dra = ((sky[m].ra - c[idx[m]].ra) * np.cos(c[idx[m]].dec.radian)).to('arcsec').value
    ddec = (sky[m].dec - c[idx[m]].dec).to('arcsec').value
    r = np.hypot(dra - np.median(dra), ddec - np.median(ddec))
    return dict(n_match=int(m.sum()), med_dra=float(np.median(dra)), med_ddec=float(np.median(ddec)),
                rms=float(1.4826 * np.median(r)), obj=obj, idx=idx, m=m, cat=c)


def run_one(frame, conn=None, force=False):
    t0 = time.time()
    row = db.get_frame(frame, conn)
    qa = FrameQA(frame, 'wcs')
    img = Path(row['filepath']) / frame
    t = db.target_info(row['targetid'], conn)
    if not t.get('gaia_cat'):
        return qa.fail('no Gaia catalog for the target (run catalogs)')
    cat = catalogs.read(config.catalog_dir('gaia') / t['gaia_cat'])
    with fits.open(img, mode='update' if force or row['wcs'] != 0 else 'readonly') as f:
        data, hdr = f[0].data, f[0].header
        res = measure(data, hdr, cat)
        refit = row['wcs'] != 0 or force
        if res is not None and not refit:
            ok = res['n_match'] >= GATES['min_matches'] and res['rms'] <= GATES['max_rms_arcsec']
            refit = not ok
        if refit and res is not None and res['n_match'] >= 6:
            from astropy.wcs.utils import fit_wcs_from_points
            m = res['m']
            new = fit_wcs_from_points((res['obj']['x'][m], res['obj']['y'][m]), res['cat'][res['idx'][m]],
                                      projection='TAN')
            f[0].header.update(new.to_header())
            f[0].header['WCSERR'] = 0
            res = measure(data, f[0].header, cat)
            qa.messages.append('WCS re-fitted to Gaia matches')
    if res is None or res['n_match'] < GATES['min_matches']:
        db.update(frame, conn, wcs=9999, quality=1)
        return qa.fail(f"too few Gaia matches ({0 if res is None else res['n_match']})")
    qa.check('n_match', res['n_match'], lo=GATES['min_matches'])
    qa.check('rms_arcsec', res['rms'], hi=GATES['max_rms_arcsec'])
    qa.check('offset_arcsec', float(np.hypot(res['med_dra'], res['med_ddec'])), hi=GATES['max_offset_arcsec'],
             severity='warn')
    qa.metrics.update(med_dra_arcsec=res['med_dra'], med_ddec_arcsec=res['med_ddec'])
    db.update(frame, conn, wcs=0 if qa.status != 'fail' else 9999)
    qa.seconds = round(time.time() - t0, 2)
    return qa
