"""Stage ``psf``: PSF model, aperture correction and the ``.sn2.fits`` field-star table.

Replaces ``lscpsf.py``/``lscpsfdef.ecpsf`` (IRAF daophot phot/pstselect/psf/group/nstar) with photutils.
The recipe and every parameter follow the old pipeline (see notes/daophot_spec.md for the IRAF rules):

* FWHM F from the header (L1FWHM/PIXSCALE) unless given; radii a1..a4 = int(k*F+0.5), k=1..4;
  apertures a2,a3,a4; sky annulus a4..a4+10 px, mean with iterative 3-sigma clipping (50 passes);
  centroid recentering in a box of 2*int(a2/2)+1 px (IRAF marginal centroid);
  datamin = -100, datamax = 0.7*SATURATE; magnitudes -2.5log10(flux/EXPTIME).
* PSF stars: catalog (Gaia by default) stars on the frame, stars with bad pixels within a4+0.5 dropped,
  brightest first (a2 magnitude), rejected if a brighter star lies within psfrad+fitrad+2, up to 6.
* PSF model (``model='daophot'``, default): pixel-integrated Gaussian (photutils GaussianPRF, no rotation)
  fitted jointly to the PSF stars within fitrad, plus a 2x oversampled lookup table of the weighted mean
  residuals (DAOPHOT recipe, varorder=0), wrapped in a photutils ImagePSF. ``model='epsf'`` uses
  photutils EPSFBuilder instead.
* Magnitude scale as DAOPHOT: a star with the model's flux has the a2-aperture magnitude of PSF star 1.
* PSF photometry: photutils PSFPhotometry (grouping at psfrad+fitrad+1, fit box 2*fitrad+1, local sky =
  aperture sky), recentering on.
* Aperture correction: mean of (a3 mag - PSF mag) over the PSF stars, 2-sigma clipped if >3 stars;
  the stage fails if |apco| > max_apercorr (0.1).
* sn2 table: every catalog star (positions rounded to 0.1 px like wcsctran %10.1f) with magp2/3/4,
  merrp3, smagf = PSF mag + apco, smagerrf; header APCO, APCOERR, XDIM, YDIM, PSF_FWHM.
"""
import logging
import time
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import SigmaClip
from astropy.table import Table
from astropy.wcs import WCS

from . import db
from .headers import readkey
from .qa import FrameQA

log = logging.getLogger(__name__)
LN2 = 0.6931472
_PRF = None

DEFAULTS = dict(fwhm=None, nstars=6, datamin=-100., datamax=None, max_apercorr=0.1, field='gaia',
                use_sextractor=False, model='daophot', threshold=5., time_budget=600.)


# --------------------------------------------------------------------------------------------------
# frame parameters
def pixscale(hdr):
    if 'PIXSCALE' in hdr:
        return float(readkey(hdr, 'PIXSCALE'))
    if 'CCDSCALE' in hdr:
        b = hdr['CCDXBIN'] if 'CCDXBIN' in hdr else int(str(hdr.get('CCDSUM', '1 1')).split()[0])
        return float(hdr['CCDSCALE']) * b
    raise KeyError('no pixel scale in header')


def header_fwhm(hdr, scale):
    """FWHM in pixels as ecpsf: L1FWHM (arcsec) if the WCS is good, else PSF_FWHM."""
    if readkey(hdr, 'wcserr') == 0:
        if 'L1FWHM' in hdr:
            seeing = float(hdr['L1FWHM'])
        elif 'L1SEEING' in hdr:
            seeing = float(hdr['L1SEEING']) * scale
        else:
            seeing = 3
    elif 'PSF_FWHM' in hdr:
        seeing = float(hdr['PSF_FWHM'])
    else:
        raise ValueError('astrometry not good')
    return seeing / scale


def radii(fwhm):
    return tuple(int(k * fwhm + 0.5) for k in (1, 2, 3, 4))


# --------------------------------------------------------------------------------------------------
# aperture photometry (IRAF phot equivalent built on photutils)
def _mctr1d(marg):
    """IRAF ap_cmmarg: centroid of the positive part of a mean-subtracted marginal (1-based index)."""
    n = len(marg)
    v = marg - marg.mean()
    pos = v > 0
    if not pos.any():
        return (1 + n) / 2.
    i = np.arange(1, n + 1)
    return float((v[pos] * i[pos]).sum() / v[pos].sum())


def iraf_centroid(data, x, y, cbox, datamin, datamax, maxiter=10):
    """Recentering as apphot centroid (cthreshold=0): box min subtracted, marginal centroids, <=10 iter.
    x, y are IRAF 1-based. Returns new (x, y, flag_badpix)."""
    ny, nx = data.shape
    h = int(cbox / 2)
    bad = False
    if x + h < 0.5 or x - h > nx + 0.5 or y + h < 0.5 or y - h > ny + 0.5:
        return x, y, True  # IRAF OffImage: box entirely off the image -> input position kept
    for _ in range(maxiter):
        c1, c2 = int(max(1, min(nx, x - h)) + 0.5), int(min(nx, max(1, x + h)) + 0.5)
        l1, l2 = int(max(1, min(ny, y - h)) + 0.5), int(min(ny, max(1, y + h)) + 0.5)
        box = data[l1 - 1:l2, c1 - 1:c2]
        if box.size == 0:
            return x, y, True
        bad = bool(box.min() < datamin or box.max() > datamax)
        box = np.maximum(box - box.min(), 0)
        xc = np.clip(_mctr1d(box.sum(axis=0) / box.shape[0]), 0.5, box.shape[1] + 0.5)
        yc = np.clip(_mctr1d(box.sum(axis=1) / box.shape[1]), 0.5, box.shape[0] + 0.5)
        nxc, nyc = c1 - 1 + xc, l1 - 1 + yc
        dx, dy = nxc - x, nyc - y
        x, y = nxc, nyc
        if abs(dx) < 1 and abs(dy) < 1:
            break
    return x, y, bad


def gauss_centroid(data, x, y, cbox, datamin, datamax, maxiter=10):
    """apphot calgorithm='gauss': 1-D Gaussian fits to the box marginals (photutils centroid_1dg)."""
    from photutils.centroids import centroid_1dg
    ny, nx = data.shape
    h = int(cbox / 2)
    bad = False
    if x + h < 0.5 or x - h > nx + 0.5 or y + h < 0.5 or y - h > ny + 0.5:
        return x, y, True  # IRAF OffImage: box entirely off the image -> input position kept
    for _ in range(maxiter):
        c1, c2 = int(max(1, min(nx, x - h)) + 0.5), int(min(nx, max(1, x + h)) + 0.5)
        l1, l2 = int(max(1, min(ny, y - h)) + 0.5), int(min(ny, max(1, y + h)) + 0.5)
        box = data[l1 - 1:l2, c1 - 1:c2]
        if box.size < 4:
            return x, y, True
        bad = bool(box.min() < datamin or box.max() > datamax)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            xc0, yc0 = centroid_1dg(box - box.min())
        if not (np.isfinite(xc0) and np.isfinite(yc0)):
            break
        nxc, nyc = c1 + float(np.clip(xc0, -0.5, box.shape[1] - 0.5)), l1 + float(np.clip(yc0, -0.5, box.shape[0] - 0.5))
        dx, dy = nxc - x, nyc - y
        x, y = nxc, nyc
        if abs(dx) < 1 and abs(dy) < 1:
            break
    return x, y, bad


def iraf_mean_sky(v, losigma=3., hisigma=3., maxiter=50):
    """apphot salgorithm='mean' (apmean.x): mean with iterative 3-sigma rejection where, on the FIRST pass,
    the cut half-width is limited by the distance from the mean to the data min and max
    (min(mean-dmin, dmax-mean, 3 sigma)); later passes use +-3 sigma. Population sigma (/N).
    Returns (sky, sigma, nsky). This first-pass rule rejects e.g. off-chip pixels in an annulus that a
    plain sigma clip keeps (verified against IRAF on lsc1m004-fa03-20240818-0142, star 16)."""
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n == 0:
        return np.nan, np.nan, 0
    dmin, dmax = v.min(), v.max()
    keep = np.ones(n, bool)
    mean, sig = v.mean(), v.std()
    mean = min(max(mean, dmin), dmax)
    if sig <= 0:
        return mean, sig, n
    for it in range(maxiter):
        if it == 0:
            lo = mean - min(mean - dmin, dmax - mean, losigma * sig)
            hi = mean + min(dmax - mean, mean - dmin, hisigma * sig)
        else:
            lo, hi = mean - losigma * sig, mean + hisigma * sig
        new = keep & ((v < lo) | (v > hi))
        if not new.any():
            break
        keep &= ~new
        if not keep.any():
            return np.nan, np.nan, 0
        w = v[keep]
        mean, sig = w.mean(), w.std()
        if sig <= 0:
            break
        mean = min(max(mean, dmin), dmax)
    return mean, sig, int(keep.sum())


def iraf_mode_sky(v, losigma=3., hisigma=3., maxiter=50, medcut_frac=0.025):
    """apphot salgorithm='mode' (apmode.x): trimmed median, mode = 3 med - 2 mean (or mean if
    mean < med), iterative +-3 sigma rejection about the mode. Returns (sky, sigma, nsky)."""
    v = np.sort(np.asarray(v, float)[np.isfinite(v)])
    n = len(v)
    if n == 0:
        return np.nan, np.nan, 0

    def tmed(a):
        k = len(a)
        mc = int(round(medcut_frac * k))
        med = (k + 1) // 2
        lo = max(1, med - mc)
        hi = min(k, med + mc) if med % 2 == 1 else min(k, med + mc + 1)
        return a[lo - 1:hi].mean()
    dmin, dmax = v[0], v[-1]
    med = np.clip(tmed(v), dmin, dmax)
    mean, sig = np.clip(v.mean(), dmin, dmax), v.std()
    mode = np.clip(mean if mean < med else 3 * med - 2 * mean, dmin, dmax)
    if sig <= 0:
        return mode, sig, n
    lo, hi = 0, n
    for it in range(maxiter):
        if it == 0:
            locut = med - min(med - dmin, dmax - med, losigma * sig)
            hicut = med + min(med - dmin, dmax - med, hisigma * sig)
        else:
            locut, hicut = mode - losigma * sig, mode + hisigma * sig
        nlo = lo + np.searchsorted(v[lo:hi], locut, side='left')
        nhi = lo + np.searchsorted(v[lo:hi], hicut, side='right')
        if nlo == lo and nhi == hi:
            break
        lo, hi = nlo, nhi
        if hi <= lo:
            return np.nan, np.nan, 0
        w = v[lo:hi]
        med = np.clip(tmed(w), dmin, dmax)
        mean, sig = np.clip(w.mean(), dmin, dmax), w.std()
        mode = np.clip(mean if mean < med else 3 * med - 2 * mean, dmin, dmax)
        if sig <= 0:
            break
    return mode, sig, hi - lo


def phot(data, xy, aps, annulus, dannulus, gain, exptime, datamin, datamax, cbox, salgorithm='mean',
         calgorithm='centroid'):
    """Recentered aperture photometry of many stars (IRAF phot). xy: (N,2) IRAF 1-based. Returns a Table.
    salgorithm 'mean' (psf stage) or 'mode' (daophot default, used by psfmag); calgorithm 'centroid' or
    'gauss' (1-D Gaussian fits to the marginals, photutils centroid_1dg)."""
    from photutils.aperture import (ApertureStats, CircularAnnulus, CircularAperture,
                                    aperture_photometry)
    ny, nx = data.shape
    xs, ys, cbad = [], [], []
    for x, y in xy:
        if calgorithm == 'gauss':
            xc, yc, b = gauss_centroid(data, x, y, cbox, datamin, datamax)
        else:
            xc, yc, b = iraf_centroid(data, x, y, cbox, datamin, datamax)
        xs.append(xc), ys.append(yc), cbad.append(b)
    xs, ys = np.array(xs), np.array(ys)
    pos0 = np.c_[xs - 1, ys - 1]  # photutils is 0-based
    badmask = (data < datamin) | (data > datamax)
    ann = CircularAnnulus(pos0, annulus, annulus + dannulus)
    # annulus pixels (centres inside, bad pixels dropped) -> IRAF 'mean' or 'mode' estimator
    masks = ann.to_mask(method='center')
    masks = masks if isinstance(masks, list) else [masks]
    est = iraf_mean_sky if salgorithm == 'mean' else iraf_mode_sky
    res = np.array([est(m.get_values(data, mask=badmask)) for m in masks], float).reshape(-1, 3)
    sky, sig, nsky = res[:, 0], res[:, 1], res[:, 2]
    out = Table({'id': np.arange(1, len(xs) + 1), 'xcenter': xs, 'ycenter': ys, 'msky': sky,
                 'stdev': sig, 'nsky': nsky, 'cbad': cbad})
    poisoned = np.full(len(xs), len(aps) + 1)  # first aperture index (1-based) containing a bad pixel
    badf = badmask.astype('float32')
    for k, r in enumerate(aps, start=1):
        ap = CircularAperture(pos0, r)
        tab = aperture_photometry(data, ap, method='exact')
        area = np.atleast_1d(ap.area_overlap(data, method='exact'))
        s = np.asarray(tab['aperture_sum'], float)
        flux = s - area * sky
        # off-image apertures are INDEF (IRAF: X-r < 0.5 or X+r > N+0.5)
        offimg = (xs - r < 0.5) | (xs + r > nx + 0.5) | (ys - r < 0.5) | (ys + r > ny + 0.5)
        # bad pixels within r+0.5 poison this and all larger apertures
        bmasks = CircularAperture(pos0, r + 0.5).to_mask(method='center')
        for j, m in enumerate(bmasks if isinstance(bmasks, list) else [bmasks]):
            if poisoned[j] <= len(aps):
                continue
            cut = m.get_values(badf)
            if cut.size and cut.max() > 0:
                poisoned[j] = k
        with np.errstate(divide='ignore', invalid='ignore'):
            err2 = area * sig ** 2 + flux / gain + sig ** 2 * area ** 2 / nsky
            merr = 1.0857 * np.sqrt(np.maximum(err2, 0)) / flux
            mag = -2.5 * np.log10(flux) + 2.5 * np.log10(exptime)
        ok = (flux > 0) & ~offimg & (poisoned > k) & np.isfinite(sky)
        out[f'flux{k}'] = flux
        out[f'mag{k}'] = np.where(ok, np.round(mag, 3), np.nan)
        out[f'merr{k}'] = np.where(ok, np.round(merr, 3), np.nan)
    out['badpix'] = poisoned <= len(aps)
    return out


# --------------------------------------------------------------------------------------------------
# PSF star selection (pstselect)
def select_psf_stars(ph, nmax, psfrad, fitrad, data, datamin, datamax):
    ny, nx = data.shape
    m = np.where(np.isfinite(ph['mag1']), ph['mag1'], -np.inf)
    order = np.argsort(m, kind='stable')
    radius = psfrad + fitrad + 2.
    chosen = []
    for n, i in enumerate(order):
        if len(chosen) >= nmax:
            break
        if not np.isfinite(ph['mag1'][i]) or not np.isfinite(ph['msky'][i]):
            continue
        x, y = ph['xcenter'][i], ph['ycenter'][i]
        if n > 0:
            bx, by = ph['xcenter'][order[:n]], ph['ycenter'][order[:n]]
            dx, dy = bx - x, by - y
            if np.any((np.abs(dy) < radius) & (dx ** 2 + dy ** 2 < radius ** 2)):
                continue
        if int(x - fitrad) < 0 or int(x + fitrad) > nx or int(y - fitrad) < 0 or int(y + fitrad) > ny:
            continue
        yy, xx = np.mgrid[1:ny + 1, 1:nx + 1][:, max(0, int(y - psfrad) - 3):int(y + psfrad) + 3,
                                              max(0, int(x - psfrad) - 3):int(x + psfrad) + 3]
        sub = data[yy - 1, xx - 1]
        r2 = (xx - x) ** 2 + (yy - y) ** 2
        infit = r2 <= fitrad ** 2
        if np.any((sub < datamin) & infit) or np.any((sub > datamax) & infit):
            continue  # bad or saturated pixel within fitrad
        chosen.append(i)
    return np.array(chosen, int)


# --------------------------------------------------------------------------------------------------
# PSF model: Gaussian (photutils GaussianPRF) + oversampled residual lookup table (DAOPHOT recipe)
def _gauss(x, y, x0, y0, bx, by, h):
    """DAOPHOT 'gauss' with height h: h * E(dx)E(dy)/(bx*by), E = pixel-integrated exp(-ln2 t^2/b^2).
    Implemented with photutils GaussianPRF (flux = h*pi/ln2 gives the same normalisation)."""
    global _PRF
    if _PRF is None:
        from photutils.psf import GaussianPRF
        _PRF = GaussianPRF()
    return _PRF.evaluate(x, y, h * np.pi / LN2, x0, y0, 2 * bx, 2 * by, 0.)


def _catmull(f, d):
    c1 = (f[2] - f[0]) / 2
    c4 = f[2] - f[1] - c1
    c2 = 3 * c4 - (f[3] - f[1]) / 2 + c1
    c3 = c4 - c2
    return d * (d * (d * c3 + c2) + c1) + f[1]


def _bicubic(img, X, Y):
    """DAOPHOT bicubic (Catmull-Rom 4x4) of img (0-based array) at IRAF 1-based (X, Y)."""
    kx, ky = int(X), int(Y)
    block = img[ky - 2:ky + 2, kx - 2:kx + 2]
    if block.shape != (4, 4):
        return np.nan
    rows = [_catmull(block[j], X - kx) for j in range(4)]
    return _catmull(np.array(rows), Y - ky)


def fit_gaussian(data, stars, sky, fitrad, beta0=1.25):
    """Joint least-squares fit of (bx, by) and per-star (x, y, H) over pixels within fitrad, with
    DAOPHOT's radial weights 5/(5+w/(1-w)) and, in a second pass, its robust 1/(1+|20 res/peak|)."""
    from scipy.optimize import least_squares
    ny, nx = data.shape
    boxes = []
    for (x, y), s in zip(stars, sky):
        lx, ly = int(x - fitrad) + 1, int(y - fitrad) + 1
        ux, uy = int(x + fitrad), int(y + fitrad)
        yy, xx = np.mgrid[max(ly, 1):min(uy, ny) + 1, max(lx, 1):min(ux, nx) + 1]
        boxes.append((xx.ravel(), yy.ravel(), data[yy - 1, xx - 1].ravel() - s))
    h0 = [max(b[2].max(), 1.) * beta0 ** 2 for b in boxes]
    p0 = np.r_[beta0, beta0, np.ravel([[x, y, h] for (x, y), h in zip(stars, h0)])]

    def resid(p, robust=None):
        bx, by = p[0], p[1]
        out = []
        for k, (xx, yy, d) in enumerate(boxes):
            x0, y0, h = p[2 + 3 * k:5 + 3 * k]
            w = ((xx - x0) ** 2 + (yy - y0) ** 2) / fitrad ** 2
            use = w < 0.999998
            wt = np.where(use, 5 / (5 + w / np.maximum(1 - w, 1e-9)), 0.)
            r = d - _gauss(xx, yy, x0, y0, bx, by, h)
            if robust is not None:
                peak = h / (bx * by)
                wt = wt / (1 + np.abs(20 * robust[k] / peak))
            out.append(np.sqrt(wt) * r)
        return np.concatenate(out)

    lb = np.r_[0.3, 0.3, np.ravel([[x - 2, y - 2, 0] for x, y in stars])]
    ub = np.r_[3 * fitrad + 5, 3 * fitrad + 5, np.ravel([[x + 2, y + 2, np.inf] for x, y in stars])]
    p0 = np.clip(p0, lb + 1e-6, ub - 1e-6)
    sol = least_squares(resid, p0, bounds=(lb, ub), x_scale='jac')
    # robust pass (DAOPHOT switches on residual down-weighting from iteration 4)
    raw = []
    for k, (xx, yy, d) in enumerate(boxes):
        x0, y0, h = sol.x[2 + 3 * k:5 + 3 * k]
        raw.append(d - _gauss(xx, yy, x0, y0, sol.x[0], sol.x[1], h))
    sol = least_squares(lambda p: resid(p, raw), sol.x, bounds=(lb, ub), x_scale='jac')
    npix = sum(len(b[0]) for b in boxes)
    peak1 = sol.x[4] / (sol.x[0] * sol.x[1])
    chi = np.sqrt(np.sum([(r / peak1) ** 2 for r in raw[0]]) / max(1, npix - (2 + 3 * len(stars))))
    fitted = sol.x[2:].reshape(-1, 3)
    return sol.x[0], sol.x[1], fitted, float(chi), npix


def build_lut(data, fitted, sky, bx, by, psfrad, fitrad, datamax, sigma_ana, npix):
    """Weighted mean of the PSF stars' residuals on a 2x grid (size 4R+3), DAOPHOT dp_fitlt (nclean=0)."""
    R = int(psfrad)
    size = 4 * R + 3
    mid = (size + 1) // 2
    ny, nx = data.shape
    nst = len(fitted)
    sumfree = np.sqrt(npix / max(1, npix - (1 + 3 * nst)))
    h1 = fitted[0, 2]
    num = np.zeros((size, size))
    den = np.zeros((size, size))
    jj, ii = np.mgrid[1:size + 1, 1:size + 1]
    incircle = (ii - mid) ** 2 + (jj - mid) ** 2 <= mid ** 2
    for i, ((x, y, h), s) in enumerate(zip(fitted, sky)):
        if h <= 0:
            continue
        x1, x2 = max(1, int(x - psfrad) - 2), min(nx, int(x + psfrad) + 3)
        y1, y2 = max(1, int(y - psfrad) - 2), min(ny, int(y + psfrad) + 3)
        yy, xx = np.mgrid[y1:y2 + 1, x1:x2 + 1]
        sub = data[y1 - 1:y2, x1 - 1:x2].astype(float).copy()
        good = sub <= datamax
        r2i = (xx - x) ** 2 + (yy - y) ** 2
        for k, (xk, yk, hk) in enumerate(fitted):  # subtract the analytic part of every PSF star
            model = _gauss(xx, yy, xk, yk, bx, by, hk)
            if k == i:
                infit = r2i < fitrad ** 2
                resid_i = np.sqrt(np.mean((sub[infit & good] - model[infit & good] - s) ** 2)) \
                    if np.any(infit & good) else 0.
            sub = np.where(good, sub - model, sub)
        resid_i /= (h * (1 / (bx * by)))
        wi = (h / h1) / (1 + (resid_i * sumfree / sigma_ana / 2) ** 2)
        # all table nodes at once (same arithmetic as the per-node loop of dp_ltinterp)
        jn, in_ = np.nonzero(incircle)
        X = x + (in_ + 1 - mid) / 2.
        Y = y + (jn + 1 - mid) / 2.
        Xs, Ys = X - (x1 - 1), Y - (y1 - 1)
        kx, ky = Xs.astype(int), Ys.astype(int)
        ok = (kx >= 2) & (kx + 2 <= sub.shape[1]) & (ky >= 2) & (ky + 2 <= sub.shape[0])
        jn, in_, Xs, Ys, kx, ky = jn[ok], in_[ok], Xs[ok], Ys[ok], kx[ok], ky[ok]
        off = np.arange(-2, 2)
        rows = (ky[:, None] + off[None, :])                       # (n, 4) 0-based rows ky-2..ky+1
        cols = (kx[:, None] + off[None, :])
        block = sub[rows[:, :, None], cols[:, None, :]]           # (n, 4, 4)
        gblock = good[rows[:, :, None], cols[:, None, :]]
        use = gblock.all(axis=(1, 2))
        dx, dy = (Xs - kx)[use], (Ys - ky)[use]
        blk = block[use]
        r = _catmull(np.moveaxis(blk, 2, 0), dx[:, None])        # along x for each of the 4 rows -> (n, 4)
        val = _catmull(r.T, dy)                                    # then along y
        np.add.at(num, (jn[use], in_[use]), wi * (val - s) / (h / h1))
        np.add.at(den, (jn[use], in_[use]), wi)
    if np.any((den <= 0) & incircle):
        # DAOPHOT: "Too few stars to compute PSF lookup tables" -> fail
        raise RuntimeError('too few stars to compute the PSF lookup table')
    return np.where(incircle, num / np.where(den > 0, den, 1), 0.), mid


class PSFModel:
    """DAOPHOT-style PSF (Gaussian + LUT) stored as a photutils ImagePSF on a 2x grid."""

    def __init__(self, bx, by, h1, lut, mid, psfmag, psfrad, fitrad, stars=None, kind='daophot', grid=None):
        self.bx, self.by, self.h1, self.lut, self.mid = bx, by, h1, lut, mid
        self.psfmag, self.psfrad, self.fitrad, self.stars, self.kind = psfmag, psfrad, fitrad, stars, kind
        if grid is None:
            n = lut.shape[0]
            off = (np.arange(1, n + 1) - mid) / 2.
            gx, gy = np.meshgrid(off, off)
            grid = _gauss(gx, gy, 0., 0., bx, by, h1) + lut
            grid[gx ** 2 + gy ** 2 > (psfrad + 0.5) ** 2] = 0.
        self.grid = grid                                  # model of PSF star 1 (counts per pixel)
        self.volume = grid.sum() / 4.                     # its total flux (2x oversampled grid)

    def photutils(self):
        from photutils.psf import ImagePSF
        return ImagePSF(self.grid / self.volume, oversampling=2)

    def mag(self, flux):
        """DAOPHOT magnitude: PSFMAG - 2.5 log10(scale), scale = flux / model volume."""
        with np.errstate(divide='ignore', invalid='ignore'):
            return self.psfmag - 2.5 * np.log10(flux / self.volume)

    def image(self):
        """seepsf: (2R+1)^2 image at integer offsets (exact table nodes), zero beyond psfrad."""
        R = int(self.psfrad)
        sl = slice(self.mid - 1 - 2 * R, self.mid + 2 * R, 2)
        img = self.grid[sl, sl].copy()
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
        img[xx ** 2 + yy ** 2 >= R ** 2] = 0
        return img

    def write(self, path, hdr_extra=None):
        h = fits.Header()
        h['FUNCTION'] = (self.kind, 'gauss+lut (daophot) or epsf')
        h['PSFHEIGH'], h['PSFMAG'] = self.h1, self.psfmag
        h['NPARS'], h['PAR1'], h['PAR2'] = 2, self.bx, self.by
        h['PSFRAD'], h['FITRAD'], h['OVERSAMP'], h['VOLUME'] = self.psfrad, self.fitrad, 2, self.volume
        if self.stars is not None:
            h['NPSFSTAR'] = len(self.stars)
            for n, s in enumerate(self.stars, start=1):
                h[f'ID{n}'], h[f'X{n}'], h[f'Y{n}'], h[f'MAG{n}'] = int(s['id']), s['x'], s['y'], s['mag']
        for k, v in (hdr_extra or {}).items():
            h[k] = v
        fits.HDUList([fits.PrimaryHDU(self.grid.astype('float32'), h),
                      fits.ImageHDU(self.lut.astype('float32'), name='LUT')]).writeto(path, overwrite=True)

    @classmethod
    def read(cls, path):
        with fits.open(path) as f:
            h = f[0].header
            lut = f['LUT'].data.astype(float) if 'LUT' in f else np.zeros_like(f[0].data)
            return cls(h['PAR1'], h['PAR2'], h['PSFHEIGH'], lut, (f[0].data.shape[0] + 1) // 2, h['PSFMAG'],
                       h['PSFRAD'], h['FITRAD'], kind=h['FUNCTION'], grid=f[0].data.astype(float))


def build_epsf(data, stars, sky, psfrad, psfmag):
    """Alternative model: photutils EPSFBuilder (2x oversampled) on the selected PSF stars."""
    from astropy.nddata import NDData
    from photutils.psf import EPSFBuilder, extract_stars
    size = 2 * int(psfrad) + 1
    tab = Table({'x': stars[:, 0] - 1, 'y': stars[:, 1] - 1})
    nd = NDData(data - np.median(sky))
    cut = extract_stars(nd, tab, size=size)
    epsf, _ = EPSFBuilder(oversampling=2, maxiters=10, progress_bar=False)(cut)
    g = epsf.data / epsf.data.sum() * 4
    # scale so the model is star 1 (matching the daophot convention); volume = flux of star 1
    m = PSFModel(np.nan, np.nan, np.nan, np.zeros_like(g), (g.shape[0] + 1) // 2, psfmag, psfrad, 0,
                 kind='epsf', grid=g)
    return m


# --------------------------------------------------------------------------------------------------
# PSF photometry (nstar)
def _with_sky(base):
    """ImagePSF + a free constant: DAOPHOT nstar's fitsky=yes (sky re-fitted within the fit region,
    on top of the phot annulus sky that is passed as local_bkg)."""
    from astropy.modeling import Fittable2DModel, Parameter

    class SkyPSF(Fittable2DModel):
        flux = Parameter(default=1)
        x_0 = Parameter(default=0)
        y_0 = Parameter(default=0)
        sky = Parameter(default=0)

        def evaluate(self, x, y, flux, x_0, y_0, sky):
            return base.evaluate(x, y, flux, x_0, y_0) + sky

        @property
        def bounding_box(self):
            b = base.copy()
            b.x_0, b.y_0 = self.x_0.value, self.y_0.value
            return b.bounding_box
    return SkyPSF()


def psf_photometry(data, model, ph, fitrad, psfrad, gain, ron, datamin, datamax, fitsky=True):
    """Fit the PSF to the stars of a phot table (recentering, groups, local sky = phot sky,
    plus a fitted sky offset when fitsky, as daopars.fitsky=yes in the old pipeline)."""
    from photutils.psf import PSFPhotometry, SourceGrouper
    ok = np.isfinite(ph['msky']) & np.isfinite(ph['xcenter'])
    ny, nx = data.shape
    ok &= (ph['xcenter'] > 0.5) & (ph['xcenter'] < nx + 0.5) & (ph['ycenter'] > 0.5) & (ph['ycenter'] < ny + 0.5)
    res = Table({'id': ph['id'], 'x': np.full(len(ph), np.nan), 'y': np.full(len(ph), np.nan),
                 'flux': np.full(len(ph), np.nan), 'flux_err': np.full(len(ph), np.nan),
                 'mag': np.full(len(ph), np.nan), 'merr': np.full(len(ph), np.nan)})
    if not ok.any():
        return res
    flux0 = np.where(np.isfinite(ph['mag1']), ph['flux1'], np.nan)
    flux0 = np.where(np.isfinite(flux0) & (flux0 > 0), flux0, 1.0)
    init = Table({'x': ph['xcenter'][ok] - 1, 'y': ph['ycenter'][ok] - 1,
                  'flux': flux0[ok],
                  'local_bkg': ph['msky'][ok]})
    mask = (data < datamin) | (data > datamax)
    err = np.sqrt(np.maximum(data, 0) / gain + (ron / gain) ** 2)
    size = 2 * int(fitrad) + 1
    pmod = _with_sky(model.photutils()) if fitsky else model.photutils()
    phot_ = PSFPhotometry(pmod, (size, size),
                          grouper=SourceGrouper(min_separation=psfrad + fitrad + 1.), fitter_maxiters=200)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        out = phot_(data, mask=mask, error=err, init_params=init)
    idx = np.flatnonzero(ok)
    res['x'][idx] = np.asarray(out['x_fit']) + 1
    res['y'][idx] = np.asarray(out['y_fit']) + 1
    res['flux'][idx] = out['flux_fit']
    res['flux_err'][idx] = out['flux_err'] if 'flux_err' in out.colnames else np.nan
    f = np.asarray(res['flux'], float)
    with np.errstate(divide='ignore', invalid='ignore'):
        res['mag'] = np.where(f > 0, np.round(model.mag(f), 3), np.nan)
        res['merr'] = np.where(f > 0, np.round(1.085736 * np.asarray(res['flux_err'], float) / f, 3), np.nan)
    return res


# --------------------------------------------------------------------------------------------------
def catalog_xy(catpath, hdr, scale_round=True):
    """Catalog stars -> IRAF logical pixels (as wcsctran: TAN only, SIP ignored, rounded to 0.1 px)."""
    from . import catalogs
    cat = catalogs.read(catpath)
    w = WCS(hdr)
    w.sip = None
    x, y = w.wcs_world2pix(np.asarray(cat['ra'], float), np.asarray(cat['dec'], float), 1)
    if scale_round:
        x, y = np.sign(x) * np.floor(np.abs(x) * 10 + 0.5) / 10, np.sign(y) * np.floor(np.abs(y) * 10 + 0.5) / 10
    return x, y, cat


def sexagesimal(ra, dec):
    """wcsctran '%13.3H %12.2h' strings."""
    from astropy.coordinates import Angle
    import astropy.units as u
    r = Angle(ra, u.deg).to_string(unit=u.hour, sep=':', precision=3, pad=False)
    d = Angle(dec, u.deg).to_string(unit=u.deg, sep=':', precision=2, pad=False, alwayssign=False)
    return np.atleast_1d(r), np.atleast_1d(d)


def ecpsf(img, catpath, fwhm=None, nstars=6, datamin=-100., datamax=None, max_apercorr=0.1,
          model='daophot', positions=None):
    """One attempt. Returns (result dict, FrameQA-like metrics). Raises on hard failures."""
    with fits.open(img) as f:
        data = f[0].data.astype(float)
        hdr = f[0].header.copy()
    scale = pixscale(hdr)
    fwhm = fwhm or header_fwhm(hdr, scale)
    a1, a2, a3, a4 = radii(fwhm)
    ny, nx = data.shape
    if datamax is None:
        datamax = 0.7 * float(readkey(hdr, 'datamax'))
    gain = float(readkey(hdr, 'gain') or 1)
    ron = float(readkey(hdr, 'ron') or 1)
    exptime = float(readkey(hdr, 'exptime'))
    if positions is None:
        cx, cy, _ = catalog_xy(catpath, hdr)
    else:
        cx, cy = positions
    infr = (cx < nx) & (cy < ny) & (cy > 0)  # as ecpsf (no x > 0 cut)
    if not infr.any():
        raise RuntimeError('no catalog objects are in the field')
    common = dict(aps=(a2, a3, a4), annulus=a4, dannulus=10., gain=gain, exptime=exptime,
                  datamin=datamin, datamax=datamax, cbox=a2)
    # One phot pass over all catalog stars (_psf2.mag); _psf.mag is its in-frame subset without stars
    # whose largest aperture has bad pixels (phot is per star, so the subset is identical).
    ph_all = phot(data, np.c_[cx, cy], **common)
    keep1 = np.flatnonzero(infr & ~np.asarray(ph_all['badpix']))
    ph1 = ph_all[keep1]
    sel = select_psf_stars(ph1, nstars, a4, a1, data, datamin, datamax)
    if len(sel) == 0:
        raise RuntimeError('no PSF stars')
    stars = np.c_[ph1['xcenter'][sel], ph1['ycenter'][sel]]
    psfmag = float(ph1['mag1'][sel[0]])
    if model == 'epsf':
        pm = build_epsf(data, stars, ph1['msky'][sel], a4, psfmag)
        chi = np.nan
    else:
        bx, by, fitted, chi, npix = fit_gaussian(data, stars, np.asarray(ph1['msky'][sel]), a1)
        lut, mid = build_lut(data, fitted, np.asarray(ph1['msky'][sel]), bx, by, a4, a1, datamax, chi, npix)
        pm = PSFModel(bx, by, fitted[0, 2], lut, mid, psfmag, a4, a1,
                      stars=[dict(id=int(ph1['id'][i]), x=float(ph1['xcenter'][i]), y=float(ph1['ycenter'][i]),
                                  mag=float(ph1['mag1'][i])) for i in sel])
    # one PSF-fitting pass over all stars (the old code ran nstar on _psf.mag and again on _psf2.mag)
    fit_all = psf_photometry(data, pm, ph_all, a1, a4, gain, ron, datamin, datamax)
    fit1 = fit_all[keep1]
    dmag = np.asarray(ph1['mag2'][sel] - fit1['mag'][sel], float)
    dmag = dmag[np.isfinite(dmag)]
    if len(dmag) == 0:
        raise RuntimeError('no aperture correction stars')
    apco, apco_err = float(np.mean(dmag)), float(np.std(dmag))
    if len(dmag) > 3:
        dmag = dmag[np.abs(dmag - np.median(dmag)) < 2 * np.std(dmag)]
        apco, apco_err = float(np.mean(dmag)), float(np.std(dmag))
    metrics = dict(fwhm_input_pix=fwhm, fwhm_input_arcsec=fwhm * scale, a1=a1, a2=a2, a3=a3, a4=a4,
                   datamax=datamax, n_catalog_infield=int(infr.sum()), n_phot_good=len(ph1),
                   n_psf_stars=len(sel), apco=apco, apco_err=apco_err, n_apco=len(dmag), model=model,
                   chi_analytic=chi)
    if model != 'epsf':
        metrics.update(fwhm_psf_x_pix=2 * pm.bx, fwhm_psf_y_pix=2 * pm.by)
    result = dict(data=data, hdr=hdr, scale=scale, fwhm=fwhm, radii=(a1, a2, a3, a4), datamin=datamin,
                  datamax=datamax, gain=gain, ron=ron, exptime=exptime, ph1=ph1, sel=sel, fit1=fit1, model=pm,
                  apco=apco, apco_err=apco_err, cx=cx, cy=cy, dmag=dmag, ph_all=ph_all, fit_all=fit_all)
    return result, metrics


def write_sn2(img, r):
    """psffit2 + sn2 table: phot + PSF fit of every catalog star, smagf = PSF mag + apco."""
    a1, a2, a3, a4 = r['radii']
    ph2, fit2 = r['ph_all'], r['fit_all']
    w = WCS(r['hdr'])
    w.sip = None
    ra, dec = w.wcs_pix2world(np.asarray(ph2['xcenter'], float), np.asarray(ph2['ycenter'], float), 1)
    ras, decs = sexagesimal(ra, dec)
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    c = SkyCoord(ras, decs, unit=(u.hourangle, u.deg))  # ra0/dec0 from the rounded strings, as deg2HMS
    smagf = np.where(np.isfinite(fit2['mag']), np.round(fit2['mag'] + r['apco'], 3), 9999.)
    smagerrf = np.where(np.isfinite(fit2['mag']), np.round(np.sqrt(fit2['merr'] ** 2 + r['apco_err'] ** 2), 3), 9999.)

    def f9999(a):
        return np.where(np.isfinite(a), a, 9999.).astype('float64')
    cols = [fits.Column(name='ra', format='20A', array=ras), fits.Column(name='dec', format='20A', array=decs),
            fits.Column(name='ra0', format='E', array=c.ra.deg), fits.Column(name='dec0', format='E', array=c.dec.deg),
            fits.Column(name='magp2', format='E', array=f9999(ph2['mag1'])),
            fits.Column(name='magp3', format='E', array=f9999(ph2['mag2'])),
            fits.Column(name='merrp3', format='E', array=f9999(ph2['merr2'])),
            fits.Column(name='magp4', format='E', array=f9999(ph2['mag3'])),
            fits.Column(name='smagf', format='E', array=smagf),
            fits.Column(name='smagerrf', format='E', array=smagerrf)]
    hdr = r['hdr'].copy()
    hdr['APCO'] = (float(np.mean(r['dmag'])), 'Aperture correction')
    hdr['APCOERR'] = (float(np.std(r['dmag'])), 'Aperture correction error')
    hdr['XDIM'] = (int(hdr['NAXIS1']), 'x number of pixels')
    hdr['YDIM'] = (int(hdr['NAXIS2']), 'y number of pixels')
    hdr['PSF_FWHM'] = (r['fwhm'] * r['scale'], 'FWHM (arcsec) - input to the psf stage')
    out = Path(str(img).replace('.fits', '.sn2.fits'))
    fits.HDUList([fits.PrimaryHDU(header=hdr), fits.BinTableHDU.from_columns(cols)]).writeto(out, overwrite=True)
    return out, ph2, fit2


def ladder(row, base):
    """Remediation attempts for a failed PSF, in the order the manual recommends (design.md 7.1)."""
    yield 'default', dict(base)
    f0 = base.get('fwhm')
    tel = row['telescope'] or ''
    if '0m4' in tel or row['filename'][3:6] == '0m4':
        for f in (5, 7):
            yield f'fwhm={f}', dict(base, fwhm=f)
    for k in (1.25, 1.5):
        yield f'fwhm x{k}', dict(base, fwhm=('header', k) if f0 is None else f0 * k)
    yield 'datamax below brightest PSF star', dict(base, datamax='below_star1')
    yield 'nstars=12', dict(base, nstars=12)
    for fld in ('apass', 'sloan'):
        yield f'field={fld}', dict(base, field=fld)


def psf_from_zogy(img, fwhm=None):
    """PyZOGY difference image: the PSF model is fitted to the ZOGY difference PSF image itself
    (lscpsf.py: image = B.zogypsf.fits, catalog zero.cat = one star at the centre, 1 PSF star,
    FWHM 5 px unless given, no sn2 table, aperture correction 0)."""
    zimg = Path(str(img).replace('.fits', '.zogypsf.fits'))
    with fits.open(zimg) as f:
        data, hdr = f[0].data.astype(float), f[0].header.copy()
    fwhm = fwhm or 5.
    a1, a2, a3, a4 = radii(fwhm)
    datamax = 0.7 * float(hdr.get('SATURATE', np.inf))
    w = WCS(hdr)
    x, y = w.wcs_world2pix([0.], [0.], 1)
    exptime = float(hdr.get('EXPTIME', 1.))
    ph = phot(data, np.c_[x, y], aps=(a2, a3, a4), annulus=a4, dannulus=10., gain=1., exptime=exptime,
              datamin=-100., datamax=datamax, cbox=a2)
    stars = np.c_[ph['xcenter'], ph['ycenter']]
    bx, by, fitted, chi, npix = fit_gaussian(data, stars, np.asarray(ph['msky']), a1)
    lut, mid = build_lut(data, fitted, np.asarray(ph['msky']), bx, by, a4, a1, datamax, chi, npix)
    pm = PSFModel(bx, by, fitted[0, 2], lut, mid, float(ph['mag1'][0]), a4, a1,
                  stars=[dict(id=1, x=float(stars[0, 0]), y=float(stars[0, 1]), mag=float(ph['mag1'][0]))])
    scale = float(hdr.get('PIXSCALE') or 1.)
    return pm, dict(fwhm_input_pix=fwhm, fwhm_input_arcsec=fwhm * scale, fwhm_psf_x_pix=2 * bx,
                    fwhm_psf_y_pix=2 * by, psfmag=pm.psfmag, apco=0., n_psf_stars=1)


def run_one(frame, conn=None, redo=False, auto_fix=True, **kw):
    """psf stage for one frame with the manual's remediation ladder; updates DB like lscpsf.py."""
    t0 = time.time()
    row = db.get_frame(frame, conn)
    img = Path(row['filepath']) / frame
    qa = FrameQA(frame, 'psf')
    psfout = Path(str(img).replace('.fits', '.psf.fits'))
    sn2out = Path(str(img).replace('.fits', '.sn2.fits'))
    done = psfout.exists() and row['psf'] != 'X' and (sn2out.exists() or row['filetype'] == 3)
    if done and not redo:  # complete products only (a run killed between the two writes is redone)
        qa.status = 'skipped'
        qa.messages.append('psf already calculated')
        return qa
    if row['filetype'] == 3 and 'optimal' in frame:
        try:
            pm, m = psf_from_zogy(img, kw.get('fwhm'))
        except Exception as e:
            db.update(frame, conn, psf='X')
            return qa.fail(f'zogy psf failed: {e}')
        pm.write(psfout, {'APCO': 0.})
        db.update(frame, conn, psf=psfout.name, fwhm=m['fwhm_input_arcsec'], mag=9999, psfmag=9999, apmag=9999,
                  apercorr=0.)
        qa.metrics.update(m)
        qa.outputs = [str(psfout)]
        qa.seconds = round(time.time() - t0, 2)
        return qa
    if row['quality'] != 127 or row['wcs'] != 0:
        qa.status = 'skipped'
        qa.messages.append(f"checkstage: quality={row['quality']} wcs={row['wcs']}")
        return qa
    opts = {**DEFAULTS, **kw}
    attempts = []
    best = None
    with fits.open(img) as f:
        hdr0 = f[0].header
    budget = float(kw.get('time_budget', 600.))  # seconds per frame for the remediation ladder
    for label, o in ladder(row, opts) if auto_fix else [('default', opts)]:
        if attempts and time.time() - t0 > budget:
            attempts.append(dict(label=label, status='not tried', message=f'time budget {budget:.0f} s used'))
            continue
        fw = o['fwhm']
        if isinstance(fw, tuple):
            fw = header_fwhm(hdr0, pixscale(hdr0)) * fw[1]
        dmax = o['datamax']
        if dmax == 'below_star1':
            if best is None or 'r' not in best:
                continue
            r = best['r']
            x, y = r['ph1']['xcenter'][r['sel'][0]], r['ph1']['ycenter'][r['sel'][0]]
            dmax = 0.99 * float(r['data'][int(y) - 2:int(y) + 1, int(x) - 2:int(x) + 1].max())
        catpath = _psf_catalog(row, o['field'], conn)
        if catpath is None:
            attempts.append(dict(label=label, status='fail', message='no catalog'))
            continue
        try:
            r, m = ecpsf(img, catpath, fw, o['nstars'], o['datamin'], dmax, o['max_apercorr'], o['model'])
        except Exception as e:
            attempts.append(dict(label=label, status='fail', message=str(e)))
            continue
        ok = abs(m['apco']) <= o['max_apercorr']
        attempts.append(dict(label=label, status='ok' if ok else 'fail', metrics=m,
                             message='' if ok else f"|apco|={abs(m['apco']):.3f} > {o['max_apercorr']}"))
        if best is None or abs(m['apco']) < abs(best['m']['apco']):
            best = dict(r=r, m=m, label=label)
        if ok:
            break
    qa.metrics['attempts'] = attempts
    if best is None or attempts[-1]['status'] != 'ok':
        db.update(frame, conn, psf='X', fwhm=0.0 if best is None else best['m']['fwhm_input_arcsec'],
                  mag=9999, psfmag=9999, apmag=9999)
        qa.fail('no PSF passed the aperture-correction gate' if best else 'psf failed: ' + attempts[-1].get('message', ''))
        qa.seconds = round(time.time() - t0, 2)
        return qa
    r, m = best['r'], best['m']
    r['model'].write(psfout, {'APCO': r['apco'], 'APCOERR': r['apco_err']})
    sn2, ph2, fit2 = write_sn2(img, r)
    db.update(frame, conn, psf=psfout.name, fwhm=m['fwhm_input_arcsec'], mag=9999, psfmag=9999, apmag=9999,
              apercorr=r['apco'])
    qa.metrics.update(m)
    qa.metrics['accepted_attempt'] = best['label']
    qa.metrics['n_sn2'] = int(np.isfinite(fit2['mag']).sum())
    qa.check('n_psf_stars', m['n_psf_stars'], lo=3, severity='warn')
    qa.outputs = [str(psfout), str(sn2)]
    qa.seconds = round(time.time() - t0, 2)
    return qa


def _psf_catalog(row, field, conn=None):
    """lscpsf.py: first available of [field, gaia, sloan, apass, landolt] compatible with the filter."""
    from . import config, sites
    t = db.target_info(row['targetid'], conn)
    for f in (field, 'gaia', 'sloan', 'apass', 'landolt'):
        if f and row['filter'] in sites.filterst[f] and t.get(f + '_cat'):
            return config.catalog_dir(f) / t[f + '_cat']
    return None
