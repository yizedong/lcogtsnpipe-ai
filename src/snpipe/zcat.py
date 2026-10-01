"""Stage ``zcat``: zero point and colour term of each frame from catalog field stars.

Port of ``lscabsphotdef.absphot`` (lscabsphotdef.py:239-556) and its helpers (``crossmatch``,
``zeropoint2``, ``transform2natural``, ``fitcol3``, ``calcZC``, ``limmag``, ``get_other_filters``) with
the lscloop defaults: field from the filter (landolt > sloan > apass priority), fixed colour terms
(Valenti et al. 2016 for Sinistro), 2-sigma rejection, ``--type fit`` (PSF mags of the sn2 table).
The arithmetic is unchanged; display/interactive branches are replaced by a review packet.
"""
import logging
import os
import time
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy import stats
from scipy.optimize import fsolve

from . import catalogs, config, db, sites
from .headers import readkey
from .qa import FrameQA

log = logging.getLogger(__name__)

FIELD_FILTERS = {'landolt': {'U', 'B', 'V', 'R', 'I'}, 'sloan': {'u', 'g', 'r', 'i', 'z'},
                 'apass': {'B', 'V', 'g', 'r', 'i'}}


def colour_terms(instrume, calib=''):
    """Fixed colour terms (``colorefisso``) selected exactly as in absphot."""
    if calib == 'sloanprime' and ('fs' in instrume or 'em' in instrume):
        return {'UUB': 0.0, 'uug': 0.0, 'BUB': 0.0, 'BBV': 0.0, 'VBV': 0.0, 'VVR': 0.0, 'gug': 0.0, 'ggr': 0.0,
                'RVR': 0.0, 'RRI': 0.0, 'rrz': 0.0, 'zrz': 0.0, 'rgr': 0.0, 'rri': 0.0, 'iri': 0.027, 'iiz': 0.0,
                'IRI': 0.0, 'ziz': 0.0}
    if calib == 'sloanprime':
        return {'UUB': 0.059, 'uug': 0.0, 'BUB': -0.095, 'BBV': 0.06, 'VBV': 0.03, 'VVR': -0.059, 'gug': 0.13,
                'ggr': 0.054, 'RVR': -0.028, 'RRI': -0.033, 'rrz': 0.0, 'zrz': 0.0, 'ggi': 0.0, 'igi': 0.0,
                'rgr': 0.003, 'rri': -0.007, 'iri': 0.028, 'iiz': 0.110, 'IRI': 0.013, 'ziz': -0.16}
    if calib == 'natural':
        return {k: 0.0 for k in ('UUB', 'uug', 'BUB', 'BBV', 'VBV', 'VVR', 'gug', 'ggr', 'RVR', 'RRI', 'rrz',
                                 'zrz', 'rgr', 'rri', 'iri', 'iiz', 'IRI', 'ziz')}
    if 'fs' in instrume or 'em' in instrume:
        return {'UUB': 0.0, 'uug': 0.0, 'BUB': 0.0, 'BBV': 0.0, 'VBV': 0.0, 'VVR': 0.0, 'gug': 0.0, 'ggr': 0.105,
                'RVR': 0.0, 'RRI': 0.0, 'rrz': 0.0, 'zrz': 0.0, 'rgr': 0.013, 'rri': 0.029, 'iri': 0.0874,
                'iiz': 0.0, 'IRI': 0.0, 'ziz': -0.15}
    if 'fl' in instrume or 'fa' in instrume:  # Valenti et al. 2016, MNRAS 459, 3939
        return {'uug': 0.0, 'ggr': 0.109, 'rri': 0.027, 'iri': 0.036, 'BBV': -0.024, 'VBV': -0.014,
                'UUB': 0.059, 'BUB': -0.095, 'VVR': -0.059, 'RVR': -0.028, 'RRI': -0.033, 'IRI': 0.013,
                'ziz': -0.04}
    if 'ep' in instrume:
        return {'uug': 0.0, 'ggr': 0.0087, 'rri': 0.0166, 'iri': 0.0217, 'BBV': 0.0, 'VBV': 0.0, 'UUB': 0.0,
                'BUB': 0.0, 'VVR': 0.0, 'RVR': 0.0, 'RRI': 0.0, 'IRI': 0.0, 'ziz': 0.0152}
    log.warning('no colour terms for %s: none applied', instrume)
    return {k: 0.0 for k in ('uug', 'gug', 'ggr', 'rgr', 'rri', 'iri', 'iiz', 'ziz', 'UUB', 'BUB', 'BBV',
                             'VBV', 'VVR', 'RVR', 'RRI', 'IRI')}


def crossmatch(ra0, dec0, ra1, dec1, tol_arcsec):
    """``lscastrodef.crossmatch``: for each (ra0,dec0) the nearest (ra1,dec1) within tol (same formula)."""
    s = np.pi / 180.
    ra0, dec0, ra1, dec1 = (np.asarray(a, float) for a in (ra0, dec0, ra1, dec1))
    pos0, pos1, dist = [], [], []
    with np.errstate(invalid='ignore'):
        for j in range(len(ra0)):
            d = np.arccos(np.sin(dec1 * s) * np.sin(dec0[j] * s) +
                          np.cos(dec1 * s) * np.cos(dec0[j] * s) * np.cos((ra1 - ra0[j]) * s))
            if len(d) and np.nanmin(d) <= tol_arcsec * np.pi / (180 * 3600):
                dist.append(np.nanmin(d))
                pos0.append(j)
                pos1.append(int(np.nanargmin(d)))
    return dist, np.array(pos0, int), np.array(pos1, int)


def zeropoint2(xx, mag, maxiter=10, nn=2):
    """Iterative mean zero point with nn-sigma rejection (unchanged algorithm)."""
    if not len(xx):
        return 9999, 9999, 9999, 9999
    data = np.array(xx - mag)
    z0, std0 = np.median(data), np.std(data)
    data1, mag1 = data[:], mag[:]
    sel = (data < z0 + nn * std0) & (data > z0 - nn * std0)
    data2, mag2 = data[sel], mag[sel]
    z2, std2 = 9999, 9999
    it = 0
    while it < maxiter and len(data2) > 5:
        z1, std1 = np.mean(data1), np.std(data1)
        z2, std2 = np.mean(data2), np.std(data2)
        if np.abs(z2 - z1) < std2 / np.sqrt(len(data2)):
            break
        s1 = (data < z1 + nn * std1) & (data > z1 - nn * std1)
        s2 = (data < z2 + nn * std2) & (data > z2 - nn * std2)
        data1, data2, mag1, mag2 = data[s1], data[s2], mag[s1], mag[s2]
        z1, std1 = np.mean(data1), np.std(data1)
        z2, std2 = np.mean(data2), np.std(data2)
        it += 1
    if np.isnan(z2):
        z2, std2 = 9999, 9999
    return z2, std2, mag2, data2


def transform2natural(cat, cterm, system):
    """Catalog magnitudes -> instrument natural system with the fixed colour terms (unchanged)."""
    c = {k: np.array(v, float) for k, v in cat.items()}

    def colour(a, b, fallback):
        return np.where((c[a] < 99) & (c[b] < 99), c[a] - c[b], c[fallback] - c[fallback])
    if system in ('sloan', 'sloanprime'):
        ug, gr, ri, iz = colour('u', 'g', 'u'), colour('g', 'r', 'g'), colour('r', 'i', 'r'), colour('i', 'z', 'i')
        c['u'] = c['u'] - cterm['uug'] * ug
        c['g'] = c['g'] - cterm['ggr'] * gr
        c['r'] = c['r'] - cterm['rri'] * ri
        c['i'] = c['i'] - cterm['iri'] * ri
        c['z'] = c['z'] - cterm['ziz'] * iz
    elif system == 'landolt':
        UB, BV, VR, RI = colour('U', 'B', 'B'), colour('B', 'V', 'B'), colour('V', 'R', 'V'), colour('R', 'I', 'R')
        c['U'] = c['U'] - cterm['UUB'] * UB
        c['B'] = c['B'] - cterm['BBV'] * BV
        c['V'] = c['V'] - cterm['VVR'] * VR
        c['R'] = c['R'] - cterm['RVR'] * VR
        c['I'] = c['I'] - cterm['IRI'] * RI
    elif system == 'apass':
        BV, gr, ri = colour('B', 'V', 'B'), colour('g', 'r', 'g'), colour('r', 'i', 'r')
        c['B'] = c['B'] - cterm['BBV'] * BV
        c['V'] = c['V'] - cterm['BBV'] * BV  # as in the old code (BBV, not VBV) — see docs/bugs.md
        c['g'] = c['g'] - cterm['ggr'] * gr
        c['r'] = c['r'] - cterm['rri'] * ri
        c['i'] = c['i'] - cterm['iri'] * ri
    return c


def _calcZC(colors, deltas, dcolors, ddeltas, keep, fixedC, guess):
    if fixedC is None:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            from scipy import odr
        out = odr.ODR(odr.Data(colors[keep], deltas[keep], wd=dcolors[keep] ** -2, we=ddeltas[keep] ** -2),
                      odr.Model(lambda B, x: B[0] + B[1] * x), beta0=guess).run()
        (Z, C), (dZ, dC) = out.beta, out.sd_beta
    elif np.any(keep):
        Z, w = np.average(deltas[keep] - fixedC * colors[keep],
                          weights=1 / (ddeltas[keep] ** 2 + dcolors[keep] ** 2), returned=True)
        dZ, C, dC = w ** -0.5, fixedC, 0
    else:
        (Z, C), dZ, dC = guess, 0, 0
    return Z, dZ, C, dC


def fitcol3(colors, deltas, dcolors, ddeltas, fixedC=None, filt='', clipsig=2):
    """Theil-Sen + clipping against individual errors, ODR or fixed-C weighted mean (unchanged logic)."""
    if fixedC is None:
        C, Z, _, _ = stats.theilslopes(deltas, colors)
        zeros = deltas - C * colors
        dzeros = (ddeltas ** 2 + (C * dcolors) ** 2) ** 0.5
        keep = abs(zeros - Z) <= clipsig * dzeros
        if sum(keep) <= 5:
            fixedC = 0.1 if filt == 'g' else 0
    if fixedC is not None:
        C = fixedC
        zeros = deltas - C * colors
        dzeros = (ddeltas ** 2 + (C * dcolors) ** 2) ** 0.5
        Z = np.median(zeros)
        keep = abs(zeros - Z) <= clipsig * dzeros
    Z, dZ, C, dC = _calcZC(colors, deltas, dcolors, ddeltas, keep, fixedC, [Z, C])
    if fixedC is None and C > 0.3:
        fixedC = 0.1 if filt == 'g' else 0
        C = fixedC
        zeros = deltas - C * colors
        dzeros = (ddeltas ** 2 + (C * dcolors) ** 2) ** 0.5
        Z = np.median(zeros)
        keep = abs(zeros - Z) <= clipsig * dzeros
        Z, dZ, C, dC = _calcZC(colors, deltas, dcolors, ddeltas, keep, fixedC, [Z, C])
    return Z, dZ, C, dC, keep


def limmag(img, zeropoint=0, nsigma=3, fwhm=5):
    """3-sigma limiting magnitude (``lscabsphotdef.limmag``), fwhm in arcsec."""
    with fits.open(img) as h:
        hdr, data = h[0].header, h[0].data
    skynoise = 1.4826 * np.median(np.abs(data - np.median(data)))
    exptime, gain, ron = readkey(hdr, 'exptime'), readkey(hdr, 'gain'), readkey(hdr, 'ron')
    radius = float(fwhm) / float(readkey(hdr, 'pixscale'))
    if not (radius and gain and skynoise):
        return 9999

    def snr(counts):
        area = np.pi * radius ** 2
        return counts * gain - nsigma * (counts * gain + (skynoise * gain) ** 2 * area + ron ** 2 * area) ** 0.5
    counts = fsolve(snr, nsigma ** 2 / gain)[0]
    return -2.5 * np.log10(counts / exptime) + zeropoint


def other_filters(frame, match_by_site=False, conn=None):
    """``get_other_filters``: filters observed the same night/target with the same telescope (or site)."""
    same = 'substr(p1.filename,1,3)=substr(p2.filename,1,3)' if match_by_site else 'p1.telescope=p2.telescope'
    rows = db.query(f'SELECT DISTINCT p2.filter FROM photlco p1, photlco p2 WHERE p1.filename=? '
                    f'AND p2.quality=127 AND p1.dayobs=p2.dayobs AND p1.targetid=p2.targetid AND {same}',
                    (frame,), conn)
    return {sites.filterst1[r['filter']] for r in rows if r['filter'] in sites.filterst1}


def find_catalog(frame_row, field='', conn=None):
    """``util.getcatalog`` by image: first field (landolt, sloan, apass) compatible with the filter."""
    t = db.target_info(frame_row['targetid'], conn)
    for f in ([field] if field else ['landolt', 'sloan', 'apass']):
        if frame_row['filter'] in sites.filterst[f] and t.get(f + '_cat'):
            return config.catalog_dir(f) / t[f + '_cat'], f
    return None, field


def read_sn2(path):
    with fits.open(path) as h:
        return h[0].header.copy(), {c: np.array(h[1].data[c]) for c in h[1].columns.names}


def run_one(frame, field='', catalogue='', fix=True, rejection=2., mtype='fit', redo=False, cutmag=99.,
            calib='', match_by_site=False, conn=None):
    t0 = time.time()
    row = db.get_frame(frame, conn)
    qa = FrameQA(frame, 'zcat')
    img = Path(row['filepath']) / frame
    sn2 = Path(str(img).replace('.fits', '.sn2.fits'))
    if row['psf'] == 'X' or row['wcs'] != 0 or not sn2.exists():
        qa.status = 'skipped'
        qa.messages.append('psf stage not done (checkstage zcat)')
        return qa
    hdr, col = read_sn2(sn2)
    if hdr.get('CATALOG') and not redo:
        qa.status = 'skipped'
        qa.messages.append('already calibrated')
        return qa
    instrume, filt = readkey(hdr, 'instrume'), readkey(hdr, 'filter')
    airmass, fwhm = readkey(hdr, 'airmass'), readkey(hdr, 'PSF_FWHM')
    kk = sites.extinction[hdr['SITEID']]
    if calib == 'apass':
        field = 'apass'
    if field == 'apass':
        calib = 'apass'
    if catalogue:
        catpath = Path(catalogue)
    else:
        catpath, field = find_catalog(row, field, conn)
    if not catpath:
        return qa.fail(f'no catalog for {filt}')
    std = catalogs.read(catpath)
    if not field:
        field = next((n for n, fs in FIELD_FILTERS.items() if fs <= set(std.colnames)), None)
    cterm = colour_terms(instrume, calib)
    db.update(frame, conn, zcat='X')

    ra, dec = col['ra0'].astype(float), col['dec0'].astype(float)
    mag, merr = (col['smagf'], col['smagerrf']) if mtype == 'fit' else (col['magp3'], col['merrp3'])
    mag, merr = mag.astype(float), merr.astype(float)
    if not cutmag or len(mag[mag < float(cutmag)]) < 5:
        cutmag = 99
    k = mag <= cutmag
    ra, dec, mag, merr = ra[k], dec[k], mag[k], merr[k]

    w = WCS(hdr)
    x, y = w.wcs_world2pix(np.asarray(std['ra'], float), np.asarray(std['dec'], float), 1)
    infield = (x > 0) & (x < readkey(hdr, 'XDIM')) & (y > 0) & (y < readkey(hdr, 'YDIM'))
    if not infield.any():
        return qa.fail('no catalog stars in the field')
    s0 = std[infield]
    _, p0, p1 = crossmatch(s0['ra'], s0['dec'], ra, dec, 5)
    s0 = s0[p0]
    f1 = sites.filterst1[filt]
    inst = mag[p1] - kk[f1] * float(airmass)
    inst_err = merr[p1]
    bands = {'landolt': 'UBVRI', 'sloan': 'ugriz', 'apass': 'BVgri'}[field]
    magstd = {b: np.asarray(s0[b], float) for b in bands}
    errstd = {b: np.asarray(s0[b + 'err'], float) for b in bands}
    if field in ('sloan', 'apass'):
        magstd['w'], errstd['w'] = magstd['r'], errstd['r']
    zero = magstd[f1] - inst
    zeroerr = (errstd[f1] ** 2 + inst_err ** 2) ** 0.5

    nat = transform2natural(magstd, cterm, field)
    zn, dzn, _, data2 = zeropoint2(np.array(nat[f1], float), inst + kk[f1] * float(airmass), 10, 2)
    updates = {}
    if zn != 9999:
        updates.update(limmag=limmag(img, zn, 3, fwhm), zn=zn, dzn=dzn, znnum=len(data2))

    colours = sites.chosecolor(other_filters(frame, match_by_site, conn) & set(magstd), False)
    colourvec = colours.get(f1, []) or [2 * f1]
    result, fits_info = {}, {}
    for c in colourvec:
        cstd = magstd[c[0]] - magstd[c[1]]
        cerr = (errstd[c[0]] ** 2 + errstd[c[1]] ** 2) ** 0.5
        maxcolor = 10 if filt in ('up', 'zs') else 2
        good = (abs(zero) < 50) & (abs(cstd) < maxcolor) & (zeroerr != 0) & (cerr != 0)
        if fix and f1 + c in cterm:
            fixed = cterm[f1 + c]
        elif c == 2 * f1:
            fixed = 0.
        else:
            fixed = None
        if not good.any():
            qa.messages.append(f'no calibration: {f1} {c} {field}')
            continue
        Z, dZ, C, dC, keep = fitcol3(cstd[good], zero[good], cerr[good], zeroerr[good], fixed, filt, rejection)
        result[f1 + c] = [Z, dZ, C, dC]
        fits_info[f1 + c] = dict(colour=cstd[good], delta=zero[good], dcolour=cerr[good], ddelta=zeroerr[good],
                                 keep=keep)

    catname = os.path.basename(catpath)
    if result:
        with fits.open(sn2, mode='update') as h:
            h[0].header['CATALOG'] = (catname, 'catalogue source')
            for ll, r in result.items():
                r = [0.0 if not np.isfinite(v) else v for v in r]
                result[ll] = r
                h[0].header['zp' + ll] = ('%3.3s %6.6s %6.6s  %6.6s  %6.6s' % (ll, r[0], r[2], r[1], r[3]),
                                          'a b sa sb in y=a+bx')
        for ll, r in result.items():
            num = 2 if ll[0] == ll[2] else (1 if ll[0] == ll[1] else None)
            updates.update({f'zcol{num}': ll[1:], f'z{num}': r[0], f'c{num}': r[2], f'dz{num}': r[1],
                            f'dc{num}': r[3], 'zcat': 'X' if r[0] == 9999 else catname})
    db.update(frame, conn, **{k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in updates.items()})

    # gates: what a human checked in `zcat -i` (enough stars, sane colour term, scatter)
    qa.metrics.update(field=field, catalog=catname, n_matched=int(len(p0)), zn=zn, dzn=dzn)
    if not result:
        qa.fail('no zero point (no colour with calibrators)')
    for ll, r in result.items():
        n_keep = int(fits_info[ll]['keep'].sum())
        qa.metrics[f'z_{ll}'], qa.metrics[f'c_{ll}'], qa.metrics[f'nkeep_{ll}'] = r[0], r[2], n_keep
        qa.check(f'nkeep_{ll}', n_keep, lo=5, severity='warn')
    qa.seconds = round(time.time() - t0, 2)
    return qa
