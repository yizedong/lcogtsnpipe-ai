"""Difference-imaging helpers: the reference PSF on the science grid, and the field-star flux ratio."""
import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table

from snpipe.diff import rebin_psf, star_flux_ratio


def gaussian(n, sigma_px):
    y, x = np.mgrid[:n, :n] - n // 2
    g = np.exp(-(x ** 2 + y ** 2) / (2 * sigma_px ** 2))
    return g / g.sum()


def moments(img):
    y, x = np.mgrid[:img.shape[0], :img.shape[1]] - img.shape[0] // 2
    f = img.sum()
    cx, cy = (x * img).sum() / f, (y * img).sum() / f
    return cx, cy, np.sqrt(((x - cx) ** 2 * img).sum() / f)


def test_rebin_psf_conserves_flux_centre_and_angular_width():
    ref = gaussian(41, 4.0)                         # 1-m reference: sigma 4 px at 0.389"/px = 1.556"
    out = rebin_psf(ref, 0.389, 0.74)               # onto a 0.4-m science grid
    cx, cy, s = moments(out)
    assert out.shape[0] % 2 == 1 and out.shape[0] < ref.shape[0]
    assert out.sum() == pytest.approx(ref.sum(), rel=1e-12)
    assert abs(cx) < 1e-9 and abs(cy) < 1e-9
    # second moment of a pixel-integrated Gaussian: sigma^2 + pixel^2/12 (in the output pixels)
    assert s == pytest.approx(np.sqrt((4.0 * 0.389 / 0.74) ** 2 + (1 / 12)), rel=0.03)


def test_rebin_psf_same_scale_is_identity():
    ref = gaussian(31, 3.0)
    assert rebin_psf(ref, 0.389, 0.3895) is ref


def sn2(path, ra, dec, mag, err):
    t = Table({'ra0': ra, 'dec0': dec, 'magp3': mag, 'merrp3': err})
    fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU(t)]).writeto(path)


def test_star_flux_ratio(tmp_path):
    rng = np.random.default_rng(1)
    ra, dec = 10 + rng.uniform(0, 0.1, 40), -5 + rng.uniform(0, 0.1, 40)
    m_ref = rng.uniform(14, 18, 40)
    # science: 0.7 mag fainter per second (clouds/smaller telescope), exposure 2x longer, 2 bad stars
    m_sci = m_ref + 0.7 + rng.normal(0, 0.005, 40)
    m_sci[:2] += 1.0
    sn2(tmp_path / 's.fits', ra, dec, m_sci, np.full(40, 0.01))
    sn2(tmp_path / 'r.fits', ra, dec, m_ref, np.full(40, 0.01))
    f, n = star_flux_ratio(tmp_path / 's.fits', tmp_path / 'r.fits', t_sci=200., t_ref=100.)
    assert n == 40 and f == pytest.approx(2 * 10 ** (-0.4 * 0.7), rel=0.005)
