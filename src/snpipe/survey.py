"""Reference images from a sky survey (Pan-STARRS1, SDSS), for fields or filters without an LCO reference.

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

SDSS (sdss_reference) is the alternative for u band and when the PS1 epoch (2010-2014) is contaminated: its
frames are single nights of 2000-2008. The old pipeline median-combined up to 50 fields from different runs (mixed
seeing); here all fields come from ONE run (one night), chosen for covering the target with good field quality and
the best seeing; the calibrated frames (nanomaggies) are combined on a TAN grid at the SDSS scale with weights from
the variance (sky + counts / gain + dark variance, per camera column, SDSS frame data model).
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
SDSS_BANDS = {**PS1_BANDS, 'up': 'u', 'u': 'u'}
LCO_FILTER = {'u': 'up', 'g': 'gp', 'r': 'rp', 'i': 'ip', 'z': 'zs'}
SDSS_SCALE = 0.396127
# PS1 mask bits treated as bad (outerspace.stsci.edu "PS1 Pixel flags in Image Table Data"): BLANK 0x0008 (no valid
# data), SAT 0x0020 (saturated or non-linear), STARCORE 0x1000 (bright star core), CONV.BAD 0x2000; the other flags
# (SUSPECT/BURNTOOL, SPIKE, GHOST, STREAK, CONV.POOR, ...) keep the pixel
PS1_BAD_BITS = 0x0008 | 0x0020 | 0x1000 | 0x2000


class SurveyError(RuntimeError):
    pass


def retry(fn, *args, tries=3, wait=30, **kw):
    """Survey archives time out now and then: try ``tries`` times, waiting longer each time."""
    import time
    for k in range(tries):
        try:
            return fn(*args, **kw)
        except Exception as e:                     # network errors of requests/astroquery/urllib
            if k == tries - 1:
                raise SurveyError(f'{getattr(fn, "__name__", fn)} failed {tries} times: {type(e).__name__}: {e}')
            log.warning('%s failed (%s), retrying in %d s', getattr(fn, '__name__', fn), e, wait * (k + 1))
            time.sleep(wait * (k + 1))


def survey_band(survey, lco_filter):
    bands = SDSS_BANDS if survey == 'sdss' else PS1_BANDS
    b = bands.get(lco_filter)
    if b is None:
        raise SurveyError(f"no {survey.upper()} reference in filter {lco_filter} ({survey.upper()} has "
                          f"{'u g r i z' if survey == 'sdss' else 'g r i z y'} only)")
    return b


def ps1_band(lco_filter):
    b = PS1_BANDS.get(lco_filter)
    if b is None:
        raise SurveyError(f'no Pan-STARRS reference in filter {lco_filter} (PS1 has g r i z y only)')
    return b


def skycells(points, band, timeout=120):
    """PS1 stack file names (image, mask, weight) of the skycells containing the given (ra, dec) points."""
    cells = {}
    for ra, dec in points:
        r = retry(requests.get, PS1_FILENAMES, timeout=timeout,
                  params=dict(ra=ra, dec=dec, filters=band, type='stack,stack.mask,stack.wt'))
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
    def get():
        r = requests.get(PS1_FITSCUT, params=dict(ra=ra, dec=dec, size=size_px, format='fits', red=filename),
                         timeout=timeout)
        r.raise_for_status()
        with fits.open(io.BytesIO(r.content)) as h:
            return h[0].data.astype('float32'), h[0].header.copy()
    return retry(get)


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
    satlev = []
    for k, cell in enumerate(cells):
        img, hdr = cutout(cell['stack'], ra, dec, size_px, timeout)
        msk, _ = cutout(cell['stack.mask'], ra, dec, size_px, timeout)
        wt, _ = cutout(cell['stack.wt'], ra, dec, size_px, timeout)
        bits = np.nan_to_num(msk, nan=0.).astype('int64')
        good = np.isfinite(img) & np.isfinite(wt) & (wt > 0) & ((bits & PS1_BAD_BITS) == 0)
        # saturated (SAT) pixels are blank (NaN) in PS1 stacks; STARCORE marks the regions around bright stars
        # (values from ~3e3 to >2e5 in a 2025rbs r stack): their median is where PS1 calls a core bright
        cores = img[((bits & 0x1000) != 0) & np.isfinite(img)]
        if cores.size:
            satlev.append(float(np.median(cores)))
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
    # noise model of the psf stage: variance = data/GAIN + (RDNOISE/GAIN)^2 (RDNOISE in electrons). A deep stack is
    # background dominated: GAIN = per-exposure gain x number of inputs (approximate effective gain), RDNOISE =
    # GAIN x median sky RMS, so the background term equals the stack's own variance image
    h['GAIN'] = float(hdr0.get('CELL.GAIN', 1.)) * h['NINPUTS']
    h['RDNOISE'] = float(h['GAIN'] * np.sqrt(np.median(var[covered])))
    # saturation level for PSF-star selection and PyZOGY: the median of the bright-star-core (STARCORE) pixels
    # (those pixels are masked anyway); without such pixels, above every valid pixel
    h['SATURATE'] = (min(satlev) if satlev else float(np.nanmax(data[covered])) * 1.01) if covered.any() else 1e9
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


def sdss_fields(ra, dec, half_deg, band, timeout=300):
    """SDSS fields (run, rerun, camcol, field, seeing, quality, mjd) whose centres lie near the field."""
    from astroquery.sdss import SDSS
    c = np.cos(np.radians(dec))
    pad = 0.2                                        # field centres up to ~0.2 deg from a covered point (13.5' x 9.8' fields on tilted stripes)
    q = (f"SELECT run, rerun, camcol, field, ra, dec, mjd_{band} AS mjd, psfWidth_{band} AS seeing, quality "
         f"FROM Field WHERE ra BETWEEN {ra - (half_deg + pad) / c} AND {ra + (half_deg + pad) / c} "
         f"AND dec BETWEEN {dec - half_deg - pad} AND {dec + half_deg + pad}")
    t = retry(SDSS.query_sql, q, timeout=timeout)
    if t is None or len(t) == 0:
        raise SurveyError('no SDSS imaging at this position')
    return t


def candidate_runs(fields, ra, dec, reach=0.25):
    """Runs (one night each) with good fields (quality >= 2) near the target, best median seeing first. Whether a
    run really covers the target is decided on its frames' WCS (sdss_reference)."""
    out = []
    for run in sorted(set(fields['run'])):
        f = fields[(fields['run'] == run) & (fields['quality'] >= 2)]
        if len(f) and np.hypot((f['ra'] - ra) * np.cos(np.radians(dec)), f['dec'] - dec).min() < reach:
            out.append((float(np.median(f['seeing'])), int(run), f))
    if not out:
        raise SurveyError('no SDSS run with good fields near the target')
    return [(run, f) for _, run, f in sorted(out, key=lambda x: x[0])]


def sdss_frame_counts(hdul, band, camcol, run):
    """An SDSS frame (nanomaggies, sky-subtracted) with its variance in nanomaggies^2: DN = image / calib,
    sky from the ALLSKY grid, variance (DN + sky) / gain + dark variance, then back to nanomaggies^2."""
    from scipy.ndimage import map_coordinates
    from ._sdss_gain import SDSS_gain_dark
    img = hdul[0].data.astype(float)
    calib = np.asarray(hdul[1].data, float)                   # nanomaggies per DN, per column
    sky = hdul[2].data
    allsky, xi, yi = sky['ALLSKY'][0], sky['XINTERP'][0], sky['YINTERP'][0]
    gx, gy = np.meshgrid(xi, yi)
    skyimg = map_coordinates(allsky, [gy, gx], order=1, mode='nearest')     # DN, shape of img
    cimg = np.broadcast_to(calib[None, :], img.shape)
    dn = img / cimg
    gain, dark = SDSS_gain_dark(int(camcol), band, int(run))
    var = (np.clip(dn + skyimg, 0, None) / gain + dark) * cimg ** 2
    return img, var, float(np.median(calib)), gain, dn + skyimg


def sdss_reference(ra, dec, size_arcsec, lco_filter, out, name='', timeout=600):
    """Download the fields of one SDSS run covering the field, combine them, write ``out`` (+ .mask/.clean)."""
    from astroquery.sdss import SDSS
    from reproject import reproject_adaptive, reproject_interp
    band = survey_band('sdss', lco_filter)
    half = size_arcsec / 7200.
    fields = sdss_fields(ra, dec, half, band)
    n = int(np.ceil(size_arcsec / SDSS_SCALE)) | 1
    w0 = WCS(naxis=2)
    w0.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    w0.wcs.crval = [ra, dec]
    w0.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w0.wcs.cdelt = [-SDSS_SCALE / 3600, SDSS_SCALE / 3600]
    centre = (n // 2, n // 2)
    for run, chosen in candidate_runs(fields, ra, dec):
        sci, wsum, sat = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n), bool)
        calibs, gains, seeing = [], [], []
        for f in chosen:
            hl = retry(SDSS.get_images, run=int(f['run']), rerun=int(f['rerun']), camcol=int(f['camcol']),
                       field=int(f['field']), band=band, timeout=timeout)
            if not hl:
                continue
            h = hl[0]
            img, var, cal, gain, counts = sdss_frame_counts(h, band, f['camcol'], f['run'])
            wf = WCS(h[0].header)
            r_img, _ = reproject_adaptive((img, wf), w0, shape_out=(n, n), conserve_flux=True)
            r_var, _ = reproject_interp((var, wf), w0, shape_out=(n, n), order='bilinear')
            # saturated: raw counts near the 16-bit limit (bias ~1000 DN); 50000 DN is a conservative threshold
            r_sat, _ = reproject_interp(((counts > 50000).astype(float), wf), w0, shape_out=(n, n), order='bilinear')
            good = np.isfinite(r_img) & np.isfinite(r_var) & (r_var > 0)
            iv = np.where(good, 1. / np.where(good, r_var, 1.), 0.)
            sci += np.where(good, r_img, 0.) * iv
            wsum += iv
            sat |= np.nan_to_num(r_sat) > 0
            calibs.append(cal)
            gains.append(gain)
            seeing.append(float(f['seeing']))
        if wsum[centre] > 0:
            break
        log.info('SDSS run %s does not cover the target, trying the next', run)
    else:
        raise SurveyError('no single SDSS run covers the target with good fields (quality >= 2): gap between camera '
                          'columns, or only BAD fields on it')
    covered = wsum > 0
    if not covered.any():
        raise SurveyError('SDSS download failed')
    data = np.where(covered, sci / np.where(covered, wsum, 1.), 0.).astype('float32')
    mask = ~covered | sat
    var = np.where(covered, 1. / np.where(covered, wsum, 1.), np.inf)
    fwhm = measure_fwhm(data, mask, SDSS_SCALE) or float(np.median(seeing))
    mjd = float(np.median(chosen['mjd']))
    t = Time(mjd, format='mjd')
    h = w0.to_header()
    h['OBJECT'] = name
    h['FILTER'] = LCO_FILTER[band]
    h['TELESCOP'], h['INSTRUME'], h['SITEID'] = 'SDSS', 'sdss', 'SDSS'
    h['SURVEY'] = ('SDSS', f'SDSS DR run {run}, frames in nanomaggies')
    h['SDSSRUN'], h['NFIELDS'] = int(run), int(len(calibs))
    h['EXPTIME'] = 53.907456                                  # SDSS drift-scan exposure per band
    h['MJD-OBS'] = mjd
    h['DATE-OBS'] = t.isot
    h['DAY-OBS'] = t.strftime('%Y%m%d')
    h['UTSTART'] = t.strftime('%H:%M:%S')
    h['AIRMASS'] = 1.
    h['PIXSCALE'] = (SDSS_SCALE, '[arcsec/pixel]')
    h['GAIN'] = float(np.median(gains) / np.median(calibs))   # electrons per nanomaggy
    h['RDNOISE'] = float(h['GAIN'] * np.sqrt(np.median(var[covered])))   # electrons, as the psf noise model expects
    h['SATURATE'] = float(np.nanmax(data)) * 1.01
    h['WCSERR'] = 0
    h['L1FWHM'] = h['PSF_FWHM'] = (fwhm, 'FWHM (arcsec)')
    h['RA'], h['DEC'], h['CAT-RA'], h['CAT-DEC'] = ra, dec, ra, dec
    h['TRACKNUM'] = 0
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(data, h).writeto(out, overwrite=True)
    fits.PrimaryHDU(data, h).writeto(str(out).replace('.fits', '.clean.fits'), overwrite=True)
    fits.PrimaryHDU(mask.astype('uint8'), h).writeto(str(out).replace('.fits', '.mask.fits'), overwrite=True)
    return dict(run=int(run), fields=int(len(calibs)), seeing_median=float(np.median(seeing)),
                coverage=float(covered.mean()), masked_fraction=float(mask.mean()), fwhm_arcsec=fwhm,
                dayobs=h['DAY-OBS'], band=band)


def build(survey, ra, dec, size_arcsec, lco_filter, out, name=''):
    return (sdss_reference if survey == 'sdss' else ps1_reference)(ra, dec, size_arcsec, lco_filter, out, name)
