"""Reference images from a sky survey (Pan-STARRS1), for fields or filters without an LCO reference.

The old pipeline (``lscloop -s ingestps1`` -> externaldata.sloanimage/sdss_swarp) mosaicked ten 41.7' PS1 cutouts
with SWarp onto a fixed LCO-like grid, with SWarp's background subtraction on (it removes part of the host galaxy
from the reference) and a crash for 0.4-m QHY frames. Here, following the approach of G. Hosseinzadeh's
image_subtraction (github.com/griffin-h/image_subtraction), with the changes listed in docs/guide/targets.md:

* one stack cutout per filter, from every PS1 skycell that the science field touches, centred on the target and
  sized to the camera's field; the stack cutouts (fitscut) are already linear (no luptitude conversion);
* no mosaic grid of our own and no background subtraction: the skycells are combined on the first cutout's pixel
  grid (PS1 0.25"/px), inverse-variance weighted, and the result is registered once, directly onto each science
  frame, by the diff stage (flux conserving, with the reference PSF resampled to the science pixels);
* PS1's own mask (blank, saturated, bright-star-core pixels) and weight (variance) images;
* a header the rest of the pipeline understands (FILTER in LCO names, PIXSCALE, measured FWHM, DAY-OBS of the
  stack's mean epoch, TELESCOP/SITEID PS1, AIRMASS 1), so the reference goes through psf, zcat and diff like an
  LCO reference image (filetype 4).

PS1 covers the sky north of declination -30 deg in g, r, i, z, y; there is no B, V or U.
"""
import io
import logging
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

log = logging.getLogger(__name__)

PS1_FILENAMES = 'https://ps1images.stsci.edu/cgi-bin/ps1filenames.py'
PS1_FITSCUT = 'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
PS1_SCALE = 0.25                                    # arcsec per pixel
MAX_SIZE_ARCSEC = 1500.                             # 25' (6000 PS1 pixels): a Sinistro field plus margin
PS1_BANDS = {'gp': 'g', 'rp': 'r', 'ip': 'i', 'zs': 'z', 'g': 'g', 'r': 'r', 'i': 'i', 'z': 'z'}
LCO_FILTER = {'g': 'gp', 'r': 'rp', 'i': 'ip', 'z': 'zs'}
# PS1 mask bits treated as bad (outerspace.stsci.edu "PS1 Pixel flags in Image Table Data"): BLANK 0x0008 (no valid
# data), SAT 0x0020 (saturated or non-linear), STARCORE 0x1000 (bright star core), CONV.BAD 0x2000; the other flags
# (SUSPECT/BURNTOOL, SPIKE, GHOST, STREAK, CONV.POOR, ...) keep the pixel
PS1_BAD_BITS = 0x0008 | 0x0020 | 0x1000 | 0x2000


class SurveyError(RuntimeError):
    pass


def ps1_band(lco_filter):
    b = PS1_BANDS.get(lco_filter)
    if b is None:
        raise SurveyError(f'no Pan-STARRS reference in filter {lco_filter} (PS1 has g r i z y only)')
    return b


def skycells(points, band, timeout=120):
    """PS1 stack file names (image, mask, weight) of the skycells containing the given (ra, dec) points."""
    cells = {}
    for ra, dec in points:
        r = requests.get(PS1_FILENAMES, params=dict(ra=ra, dec=dec, filters=band, type='stack,stack.mask,stack.wt'),
                         timeout=timeout)
        r.raise_for_status()
        from astropy.table import Table
        t = Table.read(r.text, format='ascii')
        names = {row['type']: row['filename'] for row in t}
        if 'stack' in names:
            cells[names['stack']] = names
    if not cells:
        raise SurveyError(f'no PS1 {band} stack at these positions (outside PS1, south of dec -30?)')
    return list(cells.values())


def cutout(filename, ra, dec, size_px, timeout=600):
    r = requests.get(PS1_FITSCUT, params=dict(ra=ra, dec=dec, size=size_px, format='fits', red=filename),
                     timeout=timeout)
    r.raise_for_status()
    with fits.open(io.BytesIO(r.content)) as h:
        return h[0].data.astype('float32'), h[0].header.copy()


def footprint_points(ra, dec, half_deg):
    """Target, field corners and edge mid-points: positions whose skycells cover the field."""
    c = np.cos(np.radians(dec))
    return [(ra + i * half_deg / c, dec + j * half_deg) for i in (-1, 0, 1) for j in (-1, 0, 1)]


def measure_fwhm(data, mask, scale):
    """Median FWHM (arcsec) of isolated, unsaturated point-like sources (sep)."""
    import sep
    d = np.ascontiguousarray(np.where(mask, 0., np.nan_to_num(data)), dtype='float64')
    bkg = sep.Background(d, mask=mask)
    sub = d - bkg.back()
    objs = sep.extract(sub, 10, err=bkg.globalrms, mask=mask)
    ok = (objs['flag'] == 0) & (objs['b'] / objs['a'] > 0.8) & (objs['npix'] > 10)
    peak = objs['peak'][ok]
    if ok.sum() < 5:
        return None
    sel = np.where(ok)[0][(peak > np.percentile(peak, 50)) & (peak < np.percentile(peak, 95))]
    fwhm_px = 2.3548 * np.sqrt(objs['a'][sel] * objs['b'][sel])
    return float(np.median(fwhm_px) * scale)


def ps1_reference(ra, dec, size_arcsec, lco_filter, out, name='', timeout=600):
    """Download and assemble a PS1 reference for one filter; write ``out`` (+ .mask.fits, .clean.fits).
    Returns metrics (skycells used, coverage, FWHM, masked fraction)."""
    from reproject import reproject_adaptive, reproject_interp
    band = ps1_band(lco_filter)
    size_px = int(np.ceil(size_arcsec / PS1_SCALE))
    cells = skycells(footprint_points(ra, dec, size_arcsec / 7200.), band)
    sci = wsum = None
    for k, cell in enumerate(cells):
        img, hdr = cutout(cell['stack'], ra, dec, size_px, timeout)
        msk, _ = cutout(cell['stack.mask'], ra, dec, size_px, timeout)
        wt, _ = cutout(cell['stack.wt'], ra, dec, size_px, timeout)
        bits = np.nan_to_num(msk, nan=0.).astype('int64')
        good = np.isfinite(img) & np.isfinite(wt) & (wt > 0) & ((bits & PS1_BAD_BITS) == 0)
        if k == 0:
            hdr0, w0, shape = hdr, WCS(hdr), img.shape
        else:      # same tangent plane within a projection cell: (near) identity resampling onto the first grid
            img, _ = reproject_adaptive((np.where(good, img, np.nan), WCS(hdr)), w0, shape_out=shape, conserve_flux=True)
            wt, _ = reproject_interp((np.where(good, wt, np.nan), WCS(hdr)), w0, shape_out=shape, order='bilinear')
            good = np.isfinite(img) & np.isfinite(wt) & (wt > 0)
        ivar = np.where(good, 1. / np.where(good, wt, 1.), 0.)
        if sci is None:
            sci, wsum = np.zeros(shape), np.zeros(shape)
        sci += np.where(good, img, 0.) * ivar
        wsum += ivar
    covered = wsum > 0
    data = np.where(covered, sci / np.where(covered, wsum, 1.), 0.).astype('float32')
    mask = ~covered
    var = np.where(covered, 1. / np.where(covered, wsum, 1.), np.inf)
    fwhm = measure_fwhm(data, mask, PS1_SCALE)
    mjd = float(hdr0.get('MJD-OBS', 55500.))
    t = Time(mjd, format='mjd')
    h = WCS(hdr0).to_header()
    h['OBJECT'] = name
    h['FILTER'] = LCO_FILTER[band]
    h['TELESCOP'], h['INSTRUME'], h['SITEID'] = 'PS1', 'ps1', 'PS1'
    h['SURVEY'] = ('PS1', 'Pan-STARRS1 3pi stack (ps1images.stsci.edu)')
    h['SKYCELLS'] = ','.join(c['stack'].split('/')[-1].replace('.stk.', '.').replace('.unconv.fits', '') for c in cells)[:68]
    h['NSKYCELL'] = len(cells)
    h['EXPTIME'] = float(hdr0.get('EXPTIME', 1.))
    h['NINPUTS'] = int(hdr0.get('NINPUTS', 1))
    h['MJD-OBS'] = mjd
    h['DATE-OBS'] = t.isot
    h['DAY-OBS'] = t.strftime('%Y%m%d')
    h['UTSTART'] = t.strftime('%H:%M:%S')
    h['AIRMASS'] = 1.
    h['PIXSCALE'] = (PS1_SCALE, '[arcsec/pixel]')
    # noise: background-dominated deep stack; RDNOISE carries the median sky noise (counts), GAIN the per-exposure
    # gain times the number of inputs (approximate effective gain of the stack)
    h['RDNOISE'] = float(np.sqrt(np.median(var[covered])))
    h['GAIN'] = float(hdr0.get('CELL.GAIN', 1.)) * h['NINPUTS']
    h['SATURATE'] = float(np.nanmax(data)) * 1.01 if covered.any() else 1e9   # PS1 saturated pixels are masked
    h['WCSERR'] = 0
    if fwhm:
        h['L1FWHM'] = h['PSF_FWHM'] = (fwhm, 'FWHM (arcsec), measured with sep')
    h['RA'], h['DEC'], h['CAT-RA'], h['CAT-DEC'] = ra, dec, ra, dec
    h['TRACKNUM'] = 0
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(data, h).writeto(out, overwrite=True)
    fits.PrimaryHDU(data, h).writeto(str(out).replace('.fits', '.clean.fits'), overwrite=True)
    fits.PrimaryHDU(mask.astype('uint8'), h).writeto(str(out).replace('.fits', '.mask.fits'), overwrite=True)
    return dict(skycells=[c['stack'] for c in cells], size_px=size_px, coverage=float(covered.mean()),
                masked_fraction=float(mask.mean()), fwhm_arcsec=fwhm, dayobs=h['DAY-OBS'], band=band)


def field_size(frames_paths, ra, dec, margin=1.1):
    """Side (arcsec) of a square centred on the target that contains the given science frames."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    c0, r = SkyCoord(ra, dec, unit='deg'), 0.
    for p in frames_paths:
        h = fits.getheader(p)
        w = WCS(h)
        ny, nx = h['NAXIS2'], h['NAXIS1']
        corners = w.pixel_to_world([0, nx, 0, nx], [0, 0, ny, ny])
        dra = ((corners.ra - c0.ra).wrap_at(180 * u.deg) * np.cos(c0.dec.radian)).to('arcsec').value
        ddec = (corners.dec - c0.dec).to('arcsec').value
        r = max(r, np.abs(dra).max(), np.abs(ddec).max())
    return 2 * r * margin
