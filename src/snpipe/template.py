"""Stage ``template``: mark a frame as a reference image (``B.temp.fits``, filetype 4).

Port of ``lscmaketempl.py`` for the usual case (no SN to subtract from the reference, mag = 0): the
reference is a copy of the cosmic-ray-cleaned frame (``B.clean.fits``) if it exists — unless
``uncleaned`` — else of the frame; its photlco row is built from the copy's header. The manual then runs
``cosmic`` and ``psf`` on the filetype-4 frames.
"""
import shutil
from pathlib import Path

from astropy.io import fits

from . import db, ingest
from .headers import readkey
from .qa import FrameQA


def run_one(frame, force=False, uncleaned=False, targetid=None, conn=None):
    row = db.get_frame(frame, conn)
    qa = FrameQA(frame, 'template')
    img = Path(row['filepath']) / frame
    out = Path(str(img).replace('.fits', '.temp.fits'))
    if db.get_frame(out.name, conn) and out.exists() and not force:
        qa.status = 'skipped'
        qa.messages.append('template exists')
        return qa
    src = Path(str(img).replace('.fits', '.clean.fits'))
    if uncleaned or not src.exists():
        src = img
    shutil.copy(src, out)
    hdr = fits.getheader(out)
    rec = {
        'dateobs': readkey(hdr, 'date-obs'), 'exptime': readkey(hdr, 'exptime'),
        'dayobs': hdr.get('DAY-OBS') or out.name.split('_')[2], 'filter': readkey(hdr, 'filter'),
        'targetid': targetid or row['targetid'], 'mjd': readkey(hdr, 'mjd'), 'telescope': row['telescope'],
        'airmass': readkey(hdr, 'airmass'), 'objname': readkey(hdr, 'object'), 'ut': readkey(hdr, 'ut'),
        'wcs': readkey(hdr, 'wcserr'), 'instrument': row['instrument'], 'ra0': readkey(hdr, 'RA'),
        'dec0': readkey(hdr, 'DEC'), 'filename': out.name, 'filepath': str(out.parent) + '/', 'filetype': 4,
    }
    conn = conn or db.connect()
    with conn:
        conn.execute('DELETE FROM photlco WHERE filename=?', (out.name,))
    db.insert('photlco', rec, conn)
    qa.metrics.update(source=src.name, template=out.name)
    qa.outputs = [str(out)]
    return qa
