"""Stage ``psfmag``: PSF and aperture photometry of the target.

Port of ``lscsn.py`` + ``lscsnoopy.fitsn`` (non-interactive path, lscloop defaults: x/y background order 3,
background box 4 FWHM, stamp half-size 7 FWHM, 3 background iterations, recentering on):

1. FWHM f0 = sn2 PSF_FWHM / PIXSCALE; target position = targets.ra0/dec0 -> pixels (0.1 px, TAN only).
2. Stamp of side 2*7*f0 around the target (``util.imcopy`` = astropy Cutout2D, same call).
3. Background: 2-D Legendre surface (IRAF imsurfit, xorder=yorder=3 coefficients, full cross terms, no
   rejection) fitted to the stamp outside a box of side 4*f0 on the target; inside the box the surface
   replaces the data; sn = original - sky + mean(surface).
4. fitsn: aperture photometry (apertures int(f0), int(2f0+.5), int(3f0+.5); sky annulus a3..a3+10, IRAF
   'mode'; 'gauss' recentering, cbox=4) and PSF fit (fitrad = f0, psfrad = a4, recentering, fitted sky) on
   sn; truemag = PSF mag + APCO (aperture correction of the psf stage; 0 for PyZOGY differences).
5. Three more times: surface fitted to (original - fitted star) over the whole stamp, sn rebuilt, fitsn.
6. Outputs: sn2 header PSFX1/PSFY1/PSFMAG1/PSFDMAG1/APMAG1/DAPMAG1, DB psfmag/psfdmag/psfx/psfy/apmag/
   dapmag/apercorr, and the og/rs/sf stamps (original / residual / original - fitted star) used by checkmag.
"""
import logging
import time
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.modeling import fitting, models
from astropy.nddata import Cutout2D
from astropy.wcs import WCS

from . import db, psf as P
from .headers import readkey
from .qa import FrameQA

log = logging.getLogger(__name__)
DEFAULTS = dict(xord=3, yord=3, bkg=4., size=7., niter=3, recenter=True, datamax=None, datamin=None)


def legendre_surface(img, xord, yord, use=None):
    """IRAF imsurfit (function=legendre, cross_terms=yes, no rejection): xord/yord = number of coefficients."""
    ny, nx = img.shape
    yy, xx = np.mgrid[1:ny + 1, 1:nx + 1]
    m = models.Legendre2D(x_degree=xord - 1, y_degree=yord - 1, x_domain=[1, nx], y_domain=[1, ny])
    sel = np.ones(img.shape, bool) if use is None else use
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        fit = fitting.LinearLSQFitter()(m, xx[sel], yy[sel], img[sel])
    return fit(xx, yy)


def sections_mask(shape, xb1, xb2, yb1, yb2):
    """The four imsurfit 'sections' around the box (1-based inclusive limits, as lscsn.py writes them)."""
    ny, nx = shape
    use = np.zeros(shape, bool)
    for x1, x2, y1, y2 in ((1, xb1, 1, ny), (xb2, nx, 1, ny), (xb1, xb2, 1, yb1), (xb1, xb2, yb2, ny)):
        x1, x2, y1, y2 = max(1, x1), min(nx, x2), max(1, y1), min(ny, y2)
        if x2 >= x1 and y2 >= y1:
            use[y1 - 1:y2, x1 - 1:x2] = True
    return use


def fitsn(original, sn, xy, f0, psfmodel, apco0, gain, ron, exptime, dmin, dmax, recenter=True):
    """One pass of lscsnoopy.fitsn on the stamps; xy in stamp IRAF coordinates."""
    a1, a2, a3, a4 = int(f0), int(2 * f0 + .5), int(3 * f0 + .5), int(4 * f0 + .5)
    common = dict(aps=(a1, a2, a3), annulus=a3, dannulus=10., gain=gain, exptime=exptime, datamin=dmin,
                  datamax=dmax, cbox=4, salgorithm='mode', calgorithm='gauss')
    apori = P.phot(original, xy, **common)
    ph = P.phot(sn, xy, **common)
    # allstar: fitrad = f0, psfrad = a4 (<= PSF file), sky re-fitted, recentering
    sky_tab = P.phot(sn, np.c_[ph['xcenter'], ph['ycenter']], aps=(a1,), annulus=int(a4), dannulus=11.,
                     gain=gain, exptime=exptime, datamin=dmin, datamax=dmax, cbox=4, salgorithm='mode',
                     calgorithm='gauss')
    ph['msky'] = sky_tab['msky']
    if not recenter:
        ph['xcenter'], ph['ycenter'] = xy[:, 0], xy[:, 1]
    fit = P.psf_photometry(sn, psfmodel, ph, f0, min(a4, psfmodel.psfrad), gain, ron, dmin, dmax, fitsky=True)
    # fitted star model (allstar: sn - residual)
    stars = np.zeros_like(sn)
    ok = np.isfinite(fit['flux'])
    if ok.any():
        from photutils.psf import ImagePSF  # noqa: F401  (ensures photutils loaded)
        base = psfmodel.photutils()
        yy, xx = np.mgrid[0:sn.shape[0], 0:sn.shape[1]]
        for x, y, f in zip(fit['x'][ok], fit['y'][ok], fit['flux'][ok]):
            stars += base.evaluate(xx, yy, f, x - 1, y - 1)
    with np.errstate(invalid='ignore'):
        truemag = np.asarray(fit['mag'], float) + float(apco0)
    return dict(apori=apori, ph=ph, fit=fit, truemag=truemag, stars=stars, radii=(a1, a2, a3, a4))


def run_one(frame, conn=None, redo=False, ra=None, dec=None, **kw):
    t0 = time.time()
    o = {**DEFAULTS, **kw}
    row = db.get_frame(frame, conn)
    qa = FrameQA(frame, 'psfmag')
    img = Path(row['filepath']) / frame
    sn2 = Path(str(img).replace('.fits', '.sn2.fits'))
    psffile = Path(str(img).replace('.fits', '.psf.fits'))
    if row['psf'] == 'X' or not sn2.exists() or not psffile.exists():
        qa.status = 'skipped'
        qa.messages.append('psf not computed')
        return qa
    hdr2 = fits.getheader(sn2)
    if hdr2.get('PSFMAG1') not in (None, '') and not redo:
        qa.status = 'skipped'
        qa.messages.append('psfmag already done')
        return qa
    db.update(frame, conn, psfmag=9999, psfdmag=9999, psfx=9999, psfy=9999, apmag=9999)
    with fits.open(img) as f:
        data, hdr = f[0].data.astype(float), f[0].header.copy()
    DM = 0.
    if hdr.get('CONVOL00') == 'TEMPLATE':
        DM = 2.5 * np.log10(readkey(hdr, 'exptarg')) - 2.5 * np.log10(readkey(hdr, 'exptime'))
    if 'diff' in frame and 'optimal' in frame:
        apco0 = 0.
    else:
        apco0 = float(hdr2.get('APCO') or 0.)
    scale = float(hdr2['PIXSCALE']) if 'PIXSCALE' in hdr2 else float(hdr2['CCDSCALE'])
    if 'diff' in frame and 'optimal' in frame:
        # a difference image is on the science pixel grid while its star table (and PIXSCALE) is the
        # reference's: convert the FWHM with the image's own scale (old code: reference scale, 1.9x too large
        # apertures on 0.4-m differences with a 1-m reference)
        from .psf import pixscale
        scale = pixscale(hdr)
    f0 = float(hdr2.get('PSF_FWHM') or 0) / scale or 6.
    if ra is None:
        t = db.target_info(row['targetid'], conn)
        ra, dec = t['ra0'], t['dec0']
    w = WCS(hdr)
    w.sip = None
    xs, ys = w.wcs_world2pix([ra], [dec], 1)
    xs, ys = np.floor(xs * 10 + 0.5) / 10, np.floor(ys * 10 + 0.5) / 10
    xx0, yy0 = float(xs[0]), float(ys[0])
    size = o['size']
    # util.imcopy: Cutout2D with the IRAF (1-based) centre passed as-is, size 2*size*f0
    cut = Cutout2D(data, (xx0, yy0), 2 * size * f0, wcs=WCS(hdr), mode='trim')
    original = cut.data.astype(float)
    x1, y1 = xx0 - size * f0, yy0 - size * f0
    xy = np.array([[xs[0] - x1, ys[0] - y1]])
    ny, nx = original.shape
    # initial background with the target box excluded
    leng0 = o['bkg']
    xb, yb = xy[0]
    xb1, xb2 = int(xb - f0 * leng0 / 2), int(xb + f0 * leng0 / 2)
    yb1, yb2 = int(yb - f0 * leng0 / 2), int(yb + f0 * leng0 / 2)
    bg = legendre_surface(original, o['xord'], o['yord'], sections_mask(original.shape, xb1, xb2, yb1, yb2))
    midpt = float(np.mean(bg))
    sky = original.copy()
    sky[max(yb1, 1) - 1:yb2, max(xb1, 1) - 1:xb2] = bg[max(yb1, 1) - 1:yb2, max(xb1, 1) - 1:xb2]
    sn = original - sky + midpt
    dmax = o['datamax'] if o['datamax'] is not None else float(readkey(hdr, 'datamax'))
    dmin = o['datamin'] if o['datamin'] is not None else (-np.inf if 'optimal' in frame else float(readkey(hdr, 'datamin')))
    gain, ron, exptime = float(readkey(hdr, 'gain') or 1), float(readkey(hdr, 'ron') or 0), float(readkey(hdr, 'exptime'))
    model = P.PSFModel.read(psffile)
    r = fitsn(original, sn, xy, f0, model, apco0, gain, ron, exptime, dmin, dmax, o['recenter'])
    history = [float(r['truemag'][0])]
    for _ in range(int(o['niter'])):
        skyfit = original - r['stars']
        tmp = legendre_surface(skyfit, o['xord'], o['yord'])
        midpt = float(np.mean(tmp))
        sn = original - tmp + midpt
        r = fitsn(original, sn, xy, f0, model, apco0, gain, ron, exptime, dmin, dmax, o['recenter'])
        history.append(float(r['truemag'][0]))
    fit, ph = r['fit'], r['ph']
    truemag = float(r['truemag'][0])
    merr = float(fit['merr'][0])
    ok = np.isfinite(truemag)
    psfmag = truemag - DM if ok else 9999.
    # an undefined fit error means the fit did not converge: missing (9999), not zero (max(0, nan) gave 0)
    psfdmag = merr if ok and np.isfinite(merr) and merr > 0 else 9999.
    psfx = float(fit['x'][0]) + x1 - 1 if ok else 9999.
    psfy = float(fit['y'][0]) + y1 - 1 if ok else 9999.
    apmag3 = float(ph['mag3'][0]) if np.isfinite(ph['mag3'][0]) else 9999.
    dapmag3 = float(ph['merr3'][0]) if np.isfinite(ph['merr3'][0]) else 9999.
    with fits.open(sn2, mode='update') as h:
        h0 = h[0].header
        h0['PSFX1'], h0['PSFY1'], h0['PSFMAG1'] = psfx, psfy, psfmag
        h0['PSFDMAG1'], h0['APMAG1'], h0['DAPMAG1'] = psfdmag, apmag3, dapmag3
    # checkmag stamps: original, residual (sn - fitted star), sky-fit (original - fitted star)
    for suffix, arr in (('.og.fits', original), ('.rs.fits', sn - r['stars']), ('.sf.fits', original - r['stars'])):
        fits.PrimaryHDU(arr.astype('float32'), cut.wcs.to_header()).writeto(str(img).replace('.fits', suffix),
                                                                            overwrite=True)
    db.update(frame, conn, psfmag=psfmag, psfdmag=psfdmag, psfx=psfx, psfy=psfy, apmag=apmag3,
              dapmag=dapmag3, apercorr=apco0)
    qa.metrics.update(psfmag=psfmag, psfdmag=psfdmag, apmag=apmag3, dapmag=dapmag3, apco=apco0, DM=DM,
                      psfx=psfx, psfy=psfy, fwhm_pix=f0, iterations=history,
                      recenter_shift_pix=float(np.hypot(fit['x'][0] - xy[0, 0], fit['y'][0] - xy[0, 1])) if ok else None,
                      psf_minus_ap=(psfmag - apmag3) if ok and apmag3 != 9999 else None)
    if not ok:
        qa.fail('PSF fit of the target failed (psfmag=9999)')
    else:
        # what a human looks at in checkmag: did the fit stay on the target and converge?
        qa.check('recenter_shift_pix', qa.metrics['recenter_shift_pix'], hi=max(2., f0 / 2), severity='warn')
        # beyond 2 FWHM the fit is on something else (2024pxl: good fits <= 1.8 px at the 90th percentile;
        # failed ones 37-10000 px with zero error) -> reject the PSF magnitude, as a person would in checkmag
        qa.check('recenter_shift_fwhm', qa.metrics['recenter_shift_pix'] / f0, hi=2.)
        if psfdmag >= 9999:
            qa.fail('PSF fit error undefined (fit did not converge)')
        qa.check('iteration_spread', float(np.ptp(history[1:])) if len(history) > 2 else 0., hi=0.05, severity='warn')
    qa.outputs = [str(img).replace('.fits', s) for s in ('.og.fits', '.rs.fits', '.sf.fits')]
    qa.seconds = round(time.time() - t0, 2)
    return qa
