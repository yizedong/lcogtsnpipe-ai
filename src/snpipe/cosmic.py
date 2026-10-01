"""Stage ``cosmic``: cosmic-ray cleaning with astroscrappy (L.A.Cosmic).

Exact port of ``myloopdef.run_cosmic`` + ``util.Docosmic`` (python-3 branch) with the lscloop defaults
sigclip=4.5, sigfrac=0.2, objlim=4 and astroscrappy defaults otherwise, so ``.clean.fits``/``.mask.fits``
are reproduced pixel for pixel. Differences: products are written directly next to the image (the old
code wrote them to the CWD and then moved them, which is unsafe in parallel), and frames run in a
process pool.
"""
import logging
import time

import numpy as np
from astropy.io import fits

from .headers import readkey
from .qa import FrameQA

log = logging.getLogger(__name__)
DEFAULTS = dict(sigclip=4.5, sigfrac=0.2, objlim=4.0)


def docosmic(img, sigclip=4.5, sigfrac=0.2, objlim=4.0):
    from astroscrappy import detect_cosmics
    img = str(img)
    ar, hd = fits.getdata(img, header=True)
    tel = hd.get('TELID') or hd.get('TELESCOP') or 'extdata'
    if tel in ('fts', 'ftn'):
        ar = ar.astype('float32')
        gain, sat, rdnoise = hd['GAIN'], 35000, hd['RDNOISE']
    else:
        gain = hd['GAIN'] if 'GAIN' in hd else 1
        sat = hd['SATURATE'] if 'SATURATE' in hd else 60000
        rdnoise = hd['RDNOISE'] if 'RDNOISE' in hd else 1
    if '-e91.' in img:
        ar[ar < readkey(hd, 'datamin')] = sat
        pssl = 0.
    else:
        med = np.median(ar)
        noise = 1.4826 * np.median(np.abs(ar - med))
        pssl = gain * noise ** 2 - rdnoise ** 2 / gain - med  # computed (and logged) but, as in the old
        ar[ar < -pssl] = sat                                  # python-3 path, not passed to astroscrappy
    mask, clean = detect_cosmics(ar, gain=gain, readnoise=rdnoise, sigclip=sigclip, sigfrac=sigfrac,
                                 objlim=objlim, satlevel=sat, verbose=False)
    satmask = ar > sat
    out = img.replace('.fits', '.clean.fits')
    hclean = hd.copy()
    hclean['DOCOSMIC'] = (True, 'Cosmic rejection using LACosmic')
    fits.PrimaryHDU(header=hclean, data=clean).writeto(out, overwrite=True, output_verify='fix')
    pixtype = 'float32' if 'temp' in img else 'uint8'
    fits.PrimaryHDU(header=hd, data=mask.astype(pixtype)).writeto(img.replace('.fits', '.mask.fits'),
                                                                  overwrite=True, output_verify='fix')
    fits.PrimaryHDU(header=hd, data=satmask.astype('uint8')).writeto(img.replace('.fits', '.sat.fits'),
                                                                     overwrite=True, output_verify='fix')
    return dict(gain=float(gain), saturate=float(sat), rdnoise=float(rdnoise), pssl=float(pssl),
                n_cr_pixels=int(mask.sum()), cr_fraction=float(mask.mean()), n_saturated=int(satmask.sum()))


def run_one(img, force=False, **kw):
    """One frame -> FrameQA. Templates with a variance image (SDSS/PS1) are copied, mask = zeros."""
    from pathlib import Path
    t0 = time.time()
    img = Path(img)
    qa = FrameQA(img.name, 'cosmic')
    clean, mask = Path(str(img).replace('.fits', '.clean.fits')), Path(str(img).replace('.fits', '.mask.fits'))
    if not img.exists():
        return qa.fail('image not found')
    var = Path(str(img).replace('.fits', '.var.fits'))
    if var.exists():
        ar, hd = fits.getdata(img, header=True)
        fits.PrimaryHDU(header=hd, data=ar).writeto(clean, overwrite=True)
        fits.PrimaryHDU(header=hd, data=np.zeros(ar.shape, 'uint8')).writeto(mask, overwrite=True,
                                                                             output_verify='fix')
        qa.messages.append('variance image found: copied image, empty mask')
    elif clean.exists() and mask.exists() and not force:
        qa.status = 'skipped'
        qa.messages.append('cosmic rejection already done')
    else:
        m = docosmic(img, **{**DEFAULTS, **kw})
        qa.metrics.update(m)
        # a CR fraction above 1% of the pixels usually means the image is not what lacosmic expects
        qa.check('cr_fraction', m['cr_fraction'], hi=0.01, severity='warn')
    qa.outputs = [str(clean), str(mask)]
    qa.seconds = round(time.time() - t0, 2)
    return qa
