"""Equivalences the rewrite relies on (each mirrors a check made against the old pipeline)."""
import numpy as np
import pytest


def test_fast_bad_pixel_fill_matches_pyzogy():
    """diff.fast_interpolate_bad_pixels == astropy convolve(Gaussian2DKernel(6)) used by PyZOGY."""
    from astropy.convolution import Gaussian2DKernel, convolve
    from snpipe.diff import fast_interpolate_bad_pixels
    rng = np.random.default_rng(1)
    img = rng.normal(100, 10, (300, 320))
    mask = rng.random(img.shape) < 0.02
    mask[50:70, 100:140] = True
    mask[:4] = True
    ref = convolve(np.where(mask, np.nan, img), Gaussian2DKernel(6))
    out = fast_interpolate_bad_pixels(np.ma.array(img, mask=mask))
    assert np.allclose(out[mask], ref[mask], rtol=1e-10, atol=0)
    assert np.array_equal(out[~mask], img[~mask])


def test_mctr1d_marginal_centroid():
    """IRAF ap_cmmarg: centroid of the positive part of the mean-subtracted marginal (1-based)."""
    from snpipe.psf import _mctr1d
    m = np.array([0., 1., 4., 1., 0.])
    assert _mctr1d(m) == pytest.approx(3.0)
    assert _mctr1d(np.zeros(5)) == 3.0  # no positive values -> box centre


def test_mode_sky_gaussian():
    """apphot 'mode' sky of pure Gaussian noise ~ its mean; robust to a bright tail."""
    from snpipe.psf import iraf_mode_sky
    rng = np.random.default_rng(2)
    v = np.r_[rng.normal(1000, 10, 5000), rng.normal(3000, 100, 100)]
    sky, sig, n = iraf_mode_sky(v)
    assert abs(sky - 1000) < 1.5 and 8 < sig < 12 and n < len(v)


def test_aperture_weights_match_iraf_ramp_in_the_limit():
    """photutils exact overlap vs the IRAF linear ramp: same total for a flat image to <0.5% at r>=5."""
    from photutils.aperture import CircularAperture, aperture_photometry
    img = np.ones((101, 101))
    for r in (5, 10, 15):
        yy, xx = np.mgrid[0:101, 0:101]
        d = np.hypot(xx - 50.3, yy - 50.7)
        ramp = np.clip(r + 0.5 - d, 0, 1).sum()
        ex = aperture_photometry(img, CircularAperture((50.3, 50.7), r), method='exact')['aperture_sum'][0]
        assert abs(ex - ramp) / ramp < 0.005


def test_funpack_roundtrip(tmp_path):
    """ingest.funpack: SCI becomes the primary HDU with identical pixels."""
    from astropy.io import fits
    from snpipe.ingest import funpack
    rng = np.random.default_rng(3)
    data = rng.normal(500, 20, (64, 64)).astype('float32')
    h = fits.Header()
    h['EXTNAME'] = 'SCI'
    h['OBJECT'] = 'test'
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(data, h, quantize_level=0, compression_type='GZIP_2'),
                  fits.BinTableHDU.from_columns([fits.Column('x', 'E', array=[1.])], name='CAT')]
                 ).writeto(tmp_path / 'a.fits.fz')
    funpack(tmp_path / 'a.fits.fz', tmp_path / 'a.fits')
    with fits.open(tmp_path / 'a.fits') as f:
        assert f[0].name == 'SCI' and f[1].name == 'CAT'
        assert np.array_equal(f[0].data, data)
