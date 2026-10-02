"""Stage ``diff``: PyZOGY difference imaging (lscdiff.py --difftype 1).

Same recipe and defaults as ``lscloop -s diff --difftype 1`` (normalize 't'):
* template = earliest (lowest MJD) filetype-4 frame of the same target and filter class whose
  dayobs is in ``tempdate`` and whose filename contains ``temptel``;
* both cosmic-ray masks are required; the template, its mask and footprint are resampled onto the
  target grid (old default: IRAF geomap+gregister, drizzle, fluxconserve; here: reproject on the WCS,
  ``exact`` = area overlap like drizzle with pixfrac 1, times the pixel-area ratio to conserve flux);
* PSF images of target and template from their psf stage models (``seepsf``);
* ``PyZOGY.subtract.run_subtraction(..., n_stamps=1, normalization, saturations, use_mask_for_gain)``,
  everything else at the PyZOGY defaults — with PyZOGY's slow bad-pixel interpolation (direct 49x49
  astropy convolution) replaced by an exactly equivalent separable scipy filter (verified to 1e-14);
  this is the speed fix of the SLIDE package, but keeping PyZOGY's background subtraction;
* outputs ``B.optimal.<temptel>.diff.fits`` (+ ``.ref.fits`` registered template, ``.zogypsf.fits``
  200x200 PSF, ``.sn2.fits`` copied from the template for normalize 't'), header keys TARGET, TEMPLATE,
  DIFFIM, NREGION, MASKVAL, EXPTIME/SATURATE of the template, and a filetype-3 photlco row.
"""
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from . import db, sites
from .psf import PSFModel
from .headers import readkey
from .qa import FrameQA

log = logging.getLogger(__name__)

# columns reset in the diff row (the old code reset only some of them and copied the rest of the
# target row, so stale target values leaked into diff rows — survey A bug B17; documented in docs/bugs.md)
RESET = dict(psf='X', mag=9999, dmag=9999, psfmag=9999, psfdmag=9999, apmag=9999, dapmag=9999, z1=9999, z2=9999,
             c1=9999, c2=9999, dz1=9999, dz2=9999, dc1=9999, dc2=9999, zn=9999, zcat='X', abscat='X',
             apflux=9999, dapflux=9999, psfx=9999, psfy=9999, limmag=None, apercorr=None, magtype=1)


def fast_interpolate_bad_pixels(image, median_size=6, fname=''):
    """Drop-in for ``PyZOGY.util.interpolate_bad_pixels``: astropy ``convolve`` of the NaN-filled image with
    ``Gaussian2DKernel(6)`` (49x49, nan_treatment='interpolate', boundary fill 0) == normalized separable
    Gaussian filtering with the same truncation; 50-100x faster on a 4k frame."""
    from scipy.ndimage import gaussian_filter
    data = image.astype(float).filled(np.nan)
    bad = np.ma.getmaskarray(image)
    valid = ~bad & np.isfinite(data)
    num = gaussian_filter(np.where(valid, data, 0.), median_size, mode='constant', cval=0., truncate=4.)
    den = gaussian_filter(valid.astype(float), median_size, mode='constant', cval=1., truncate=4.)
    with np.errstate(invalid='ignore', divide='ignore'):
        data[bad] = (num / den)[bad]
    return data


def patch_pyzogy():
    from ._pyzogy import util as zu
    zu.interpolate_bad_pixels = fast_interpolate_bad_pixels


def register(template, tmask, thdr, target_hdr, shape, method='adaptive'):
    """Template (+mask) onto the target grid; returns (data, mask, footprint).

    adaptive (default): reproject_adaptive(conserve_flux=True) — anti-aliased, flux conserving, the closest
    analogue of IRAF gregister drizzle + fluxconserve; ~40 s for a 4k frame.
    exact: reproject_exact (area overlap) x pixel-area ratio — very slow on 4k frames.
    bilinear/bicubic: reproject_interp x pixel-area ratio (the old --no_iraf path, without its flux bug)."""
    from astropy.wcs.utils import proj_plane_pixel_area
    from reproject import reproject_adaptive, reproject_exact, reproject_interp
    wt, wtemp = WCS(target_hdr), WCS(thdr)
    if method == 'adaptive':
        data, foot = reproject_adaptive((template, wtemp), wt, shape_out=shape, conserve_flux=True)
    else:
        if method == 'exact':
            data, foot = reproject_exact((template, wtemp), wt, shape_out=shape, parallel=False)
        else:
            data, foot = reproject_interp((template, wtemp), wt, shape_out=shape, order=method)
        data = data * proj_plane_pixel_area(wt) / proj_plane_pixel_area(wtemp)
    m, _ = reproject_interp((tmask.astype(float), wtemp), wt, shape_out=shape, order='bilinear')
    # As the default (IRAF gregister) path of lscdiff: the registered CR mask only; pixels outside the
    # template footprint are 0 (boundary='constant') but NOT masked. Masking the footprint (the --no_iraf
    # path) leaves large masked areas that PyZOGY's 49x49 bad-pixel blur cannot fill (NaN -> gain fit fails).
    mask = np.nan_to_num(m) > 0
    data = np.where(foot > 0, np.nan_to_num(data), 0.)
    return data, mask, foot


def find_template(row, tempdate, temptel, conn=None):
    d1, d2 = tempdate.split('-')[0], tempdate.split('-')[-1]
    f1 = sites.filterst1.get(row['filter'])
    rows = db.query('SELECT * FROM photlco WHERE filetype=4 AND targetid=? AND dayobs>=? AND dayobs<=? '
                    'AND filename LIKE ? ORDER BY mjd', (row['targetid'], d1, d2, f'%{temptel}%'), conn)
    rows = [r for r in rows if sites.filterst1.get(r['filter']) == f1 and r['quality'] == 127]
    return rows[0] if rows else None


def run_one(frame, tempdate='19990101-20080101', temptel='', normalize='t', unmask=False, force=False,
            register_method='adaptive', region='full', cutout_size=2048, conn=None):
    t0 = time.time()
    row = db.get_frame(frame, conn)
    qa = FrameQA(frame, 'diff')
    img = Path(row['filepath']) / frame
    temptel = temptel or row['instrument'][:2]
    suffix = f'.optimal.{temptel}{".cut" if region == "cutout" else ""}.diff.fits'.replace('..', '.')
    out = Path(str(img).replace('.fits', suffix))
    if out.exists() and not force:
        qa.status = 'skipped'
        qa.messages.append('difference exists')
        return qa
    if row['psf'] == 'X' or row['wcs'] != 0:
        qa.status = 'skipped'
        qa.messages.append('target psf/wcs not done')
        return qa
    trow = find_template(row, tempdate, temptel, conn)
    if trow is None:
        return qa.fail('template not found')
    timg = Path(trow['filepath']) / trow['filename']
    tmask_f = Path(str(timg).replace('.fits', '.mask.fits'))
    mask_f = Path(str(img).replace('.fits', '.mask.fits'))
    if not mask_f.exists() or not tmask_f.exists():
        return qa.fail('cosmic-ray mask missing (run cosmic on target and template)')
    tpsf_f = Path(str(timg).replace('.fits', '.psf.fits'))
    psf_f = Path(str(img).replace('.fits', '.psf.fits'))
    if not tpsf_f.exists():
        return qa.fail('template psf missing (run psf on filetype 4)')
    with fits.open(img) as f:
        data, hdr = f[0].data.astype(float), f[0].header.copy()
    with fits.open(timg) as f:
        tdata, thdr = f[0].data.astype(float), f[0].header.copy()
    mask = fits.getdata(mask_f) > 0
    tmask = fits.getdata(tmask_f) > 0
    if region == 'cutout':
        # ASTRA decision diff_region=cutout: subtract a cutout_size^2 region around the target only
        # (4x fewer pixels for 2048 on a 4k frame; the gain fit then uses the stars of that region)
        from astropy.nddata import Cutout2D
        t = db.target_info(row['targetid'], conn)
        x0, y0 = WCS(hdr).wcs_world2pix([t['ra0']], [t['dec0']], 0)
        if min(data.shape) > cutout_size:
            c = Cutout2D(data, (float(x0[0]), float(y0[0])), cutout_size, wcs=WCS(hdr), mode='partial',
                         fill_value=np.nan)
            cm = Cutout2D(mask.astype('uint8'), (float(x0[0]), float(y0[0])), cutout_size, mode='partial',
                          fill_value=1)
            bad = ~np.isfinite(c.data)
            data, mask = np.where(bad, 0., c.data), (cm.data > 0) | bad
            h2 = hdr.copy()
            for k in [k for k in h2 if k.startswith(('CRPIX', 'NAXIS', 'PC', 'CD', 'CRVAL', 'CTYPE', 'A_', 'B_'))]:
                h2.remove(k, ignore_missing=True, remove_all=True)
            h2.update(c.wcs.to_header())
            h2['CUTOUT'] = (f'{c.origin_original[0]},{c.origin_original[1]}', 'x0,y0 (0-based) in the target frame')
            hdr = h2
    sat_targ, sat_temp = float(readkey(hdr, 'datamax')), float(readkey(thdr, 'datamax'))
    t1 = time.time()
    rdata, rmask, foot = register(tdata, tmask, thdr, hdr, data.shape, register_method)
    t_reg = time.time() - t1
    patch_pyzogy()
    from ._pyzogy.subtract import run_subtraction
    scratch = os.getenv('SNPIPE_SCRATCH') or None  # fast local disk for the ~0.4 GB of per-frame scratch FITS
    with tempfile.TemporaryDirectory(dir=scratch, ignore_cleanup_errors=True) as tmp:  # per-frame, parallel-safe
        tmp = Path(tmp)
        fits.PrimaryHDU(data, hdr).writeto(tmp / '_targ.fits')
        fits.PrimaryHDU(rdata, hdr).writeto(tmp / '_temp.fits')
        fits.PrimaryHDU(mask.astype('uint8'), hdr).writeto(tmp / '_targmask.fits')
        fits.PrimaryHDU(rmask.astype('uint8'), hdr).writeto(tmp / '_tempmask.fits')
        fits.PrimaryHDU(PSFModel.read(psf_f).image()).writeto(tmp / '_targpsf.fits')
        fits.PrimaryHDU(PSFModel.read(tpsf_f).image()).writeto(tmp / '_temppsf.fits')
        t1 = time.time()
        records = []

        class _Grab(logging.Handler):
            def emit(self, rec):
                records.append(rec.getMessage())
        grab = _Grab(level=logging.WARNING)
        logging.getLogger().addHandler(grab)
        try:
            run_subtraction(str(tmp / '_targ.fits'), str(tmp / '_temp.fits'), str(tmp / '_targpsf.fits'),
                            str(tmp / '_temppsf.fits'), science_mask=str(tmp / '_targmask.fits'),
                            reference_mask=str(tmp / '_tempmask.fits'), science_saturation=sat_targ,
                            reference_saturation=sat_temp, n_stamps=1, output=str(tmp / '_out.fits'),
                            normalization=normalize, show=False, use_mask_for_gain=not unmask)
        except Exception as e:
            msg = '; '.join([f'{type(e).__name__}: {e}'] + records[-3:])
            if not unmask:  # manual: "most of these issues are solved by adding the --unmask flag"
                q2 = run_one(frame, tempdate, temptel, normalize, True, force, register_method, conn)
                q2.messages.insert(0, f'first attempt failed ({msg}) -> retried with unmask (manual remedy)')
                return q2
            return qa.fail(f'PyZOGY failed: {msg}')
        finally:
            logging.getLogger().removeHandler(grab)
        t_zogy = time.time() - t1
        with fits.open(tmp / '_out.fits') as dh0:
            dh = fits.HDUList([h.copy() for h in dh0])
        dhdr = dh[0].header
        dhdr['TARGET'], dhdr['TEMPLATE'], dhdr['DIFFIM'] = frame, trow['filename'], out.name
        dhdr['NREGION'], dhdr['MASKVAL'] = 1, 1e-30
        dhdr['EXPTEMP'], dhdr['EXPTARG'] = float(readkey(thdr, 'exptime')), float(readkey(hdr, 'exptime'))
        if normalize == 't':
            dhdr['EXPTIME'], dhdr['SATURATE'] = float(readkey(thdr, 'exptime')), sat_temp
        dh.writeto(out, overwrite=True)
        fits.PrimaryHDU(rdata.astype('float32'), hdr).writeto(str(out).replace('.diff.', '.ref.'), overwrite=True)
        p = fits.getdata(tmp / '_out.psf.fits')
        cy, cx = np.array(p.shape) // 2
        p = p[max(cy - 100, 0):cy + 100, max(cx - 100, 0):cx + 100]
        ph = fits.Header()
        ph['CRPIX1'] = ph['CRPIX2'] = 100
        ph['CRVAL1'] = ph['CRVAL2'] = 0
        ph['CD1_1'] = ph['CD2_2'] = 1
        ph['CD1_2'] = ph['CD2_1'] = 0
        ph['PIXSCALE'] = hdr.get('PIXSCALE')
        ph['EXPTIME'] = dhdr['EXPTIME']
        ph['SATURATE'] = dhdr.get('SATURATE', sat_targ)
        fits.PrimaryHDU(p, ph).writeto(str(out).replace('.fits', '.zogypsf.fits'), overwrite=True)
    # sn2 of the normalization image
    src_sn2 = Path(str(timg if normalize == 't' else img).replace('.fits', '.sn2.fits'))
    if src_sn2.exists():
        dst = Path(str(out).replace('.fits', '.sn2.fits'))
        shutil.copy(src_sn2, dst)
        with fits.open(dst, mode='update') as h:
            for k in ('PSFMAG1', 'PSFDMAG1', 'APMAG1', 'DAPMAG1', 'PSFX1', 'PSFY1', 'CATALOG'):
                h[0].header.remove(k, ignore_missing=True, remove_all=True)
            for k in list(h[0].header):
                if k.startswith('ZP'):
                    h[0].header.remove(k, remove_all=True)
    rec = {k: v for k, v in row.items() if k not in ('id', 'datecreated', 'lastmodified')}
    rec.update(RESET)
    rec.update(filename=out.name, filepath=str(out.parent) + '/', filetype=3, difftype=1,
               exptime=float(dhdr['EXPTIME']))
    conn = conn or db.connect()
    with conn:
        conn.execute('DELETE FROM photlco WHERE filename=?', (out.name,))
        conn.execute('DELETE FROM photpairing WHERE nameout=?', (out.name,))
    db.insert('photlco', {k: v for k, v in rec.items() if v is not None}, conn)
    db.insert('photpairing', dict(namein=frame, tablein='photlco', nameout=out.name, tableout='photlco',
                                  nametemplate=trow['filename'], tabletemplate='photlco'), conn)
    # agent-checkable residual statistics: robust std of the difference vs expected noise, at field stars
    d = fits.getdata(out).astype(float)
    good = ~(mask | rmask) & np.isfinite(d)
    sig = 1.4826 * np.median(np.abs(d[good] - np.median(d[good])))
    qa.metrics.update(template=trow['filename'], register_seconds=round(t_reg, 1), zogy_seconds=round(t_zogy, 1),
                      diff_median=float(np.median(d[good])), diff_mad_sigma=float(sig),
                      masked_fraction=float(1 - good.mean()), unmask=unmask)
    qa.metrics['region'] = region
    qa.check('masked_fraction', qa.metrics['masked_fraction'], hi=0.5, severity='warn')
    qa.outputs = [str(out), str(out).replace('.fits', '.zogypsf.fits')]
    qa.seconds = round(time.time() - t0, 2)
    return qa
