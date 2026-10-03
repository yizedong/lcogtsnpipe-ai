"""Stage ``ingest``: download BANZAI frames from the LCO archive (or take local files) and register them.

Port of ``LCOGTingest.py`` + ``mysqldef.ingestredu``/``targimg``:
* archive query: one request with ``limit=5000`` (as ``LCOGTingest.get_metadata``; the API's paging
  fields are unreliable), downloads streamed to disk in parallel threads;
* files land in ``data/<lsc|0m4|fts>/YYYYMMDD/`` and are unpacked like ``funpack -D`` (SCI becomes the
  primary HDU, CAT and BPM follow) so they are byte-compatible with the old pipeline's inputs;
* photlco row with the same columns; target found by name, else by coordinates within 0.01 deg,
  else created (``targimg``).
"""
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits

from . import config, db
from .headers import readkey

log = logging.getLogger(__name__)
API = 'https://archive-api.lco.global/frames/'


def _auth():
    key = os.getenv('LCO_API_KEY')
    return {'Authorization': 'Token ' + key} if key else {}


def query_archive(limit=5000, **params):
    params = {k: v for k, v in params.items() if v is not None}
    params['limit'] = limit
    r = requests.get(API, params=params, headers=_auth(), timeout=600)
    r.raise_for_status()
    frames = r.json()['results']
    if len(frames) == limit:
        log.warning('number of frames returned equals the limit (%d); there may be more', limit)
    return frames


def funpack(src, dst):
    """``funpack -D`` equivalent: decompress tiles, SCI -> primary HDU, keep the other extensions."""
    with fits.open(src) as hdul:
        out = fits.HDUList()
        for hdu in hdul:
            if isinstance(hdu, fits.PrimaryHDU) and hdu.data is None and len(hdul) > 1:
                continue  # the empty primary of a .fz file is dropped, as funpack does
            if isinstance(hdu, fits.CompImageHDU):
                data, hdr = hdu.data, hdu.header.copy()
                for k in ('XTENSION', 'PCOUNT', 'GCOUNT'):
                    hdr.remove(k, ignore_missing=True)
                hdu = (fits.PrimaryHDU if not out else fits.ImageHDU)(data=data, header=hdr)
            elif not out and isinstance(hdu, fits.ImageHDU):
                hdu = fits.PrimaryHDU(data=hdu.data, header=hdu.header)
            out.append(hdu)
        tmp = Path(str(dst) + '.part')
        out.writeto(tmp, overwrite=True, output_verify='silentfix')
    os.replace(tmp, dst)


def place_frame(frame, src=None):
    """Download (or copy from ``src``) one frame into its day directory and unpack it. Returns the .fits path."""
    d = config.daydir(frame['TELID'], frame['INSTRUME'], frame['filename'])
    d.mkdir(parents=True, exist_ok=True)
    out = d / frame['filename'].replace('.fz', '')
    if out.exists():
        return out
    packed = d / frame['filename']
    if src is not None:
        shutil.copy(src, packed)
    else:
        with requests.get(frame['url'], stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(str(packed) + '.part', 'wb') as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        os.replace(str(packed) + '.part', packed)
    if packed.suffix == '.fz':
        funpack(packed, out)
        packed.unlink()
    return out


def find_or_create_target(hdr, conn=None):
    """``mysqldef.targimg``: by OBJECT name, else coordinates within 0.01 deg (adds the name), else new target."""
    obj = readkey(hdr, 'object')
    ra, dec = readkey(hdr, 'CAT-RA'), readkey(hdr, 'CAT-DEC')
    tid = db.target_by_name(obj, conn)
    if tid:
        return tid
    if not isinstance(ra, float) or not isinstance(dec, float):
        raise ValueError(f'no target named {obj!r} and no usable CAT-RA/CAT-DEC; add the target first')
    tid = db.target_by_coords(ra, dec, 0.01, conn)
    if tid:
        log.info('target at %.6f %.6f with a different name: adding name %s', ra, dec, obj)
    else:
        tid = db.insert('targets', {'ra0': ra, 'dec0': dec}, conn)
        log.info('new target %s id=%s at %.6f %.6f', obj, tid, ra, dec)
    db.insert('targetnames', {'name': obj, 'targetid': tid, 'groupidcode': 32769}, conn)
    return tid


def add_target(name, ra, dec, conn=None):
    """Register a target with known coordinates (what SNEx provides to the old pipeline). An existing target gets
    the given coordinates if they differ (a corrected position); returns (id, moved in arcsec or None)."""
    tid = db.target_by_name(name, conn)
    if tid is None:
        tid = db.insert('targets', {'ra0': ra, 'dec0': dec}, conn)
        db.insert('targetnames', {'name': name, 'targetid': tid, 'groupidcode': 32769}, conn)
        return tid, None
    old = db.target_info(tid, conn)
    moved = 3600 * float(np.hypot((ra - old['ra0']) * np.cos(np.radians(dec)), dec - old['dec0']))
    if moved > 0.01:
        with (conn or db.connect()):
            (conn or db.connect()).execute('UPDATE targets SET ra0=?, dec0=? WHERE id=?', (ra, dec, tid))
        log.warning('target %s moved by %.2f arcsec to %.6f %.6f', name, moved, ra, dec)
    return tid, moved


def register(path, filetype=1, force=False, targetid=None, conn=None):
    """``mysqldef.ingestredu`` for one unpacked frame: insert its photlco row. ``targetid`` (from a target file)
    attaches the frame to that target whatever its OBJECT; otherwise the target is found as ``targimg`` does."""
    path = Path(path)
    if db.get_frame(path.name, conn) and not force:
        return False
    hdr = fits.getheader(path)
    tel = hdr.get('TELESCOP') or ''
    tel = {'Faulkes Telescope South': '2m0-02', 'fts': '2m0-02',
           'Faulkes Telescope North': '2m0-01', 'ftn': '2m0-01'}.get(tel, tel)
    try:
        track = int(readkey(hdr, 'TRACKNUM'))
    except (TypeError, ValueError):
        track = 0
    row = {
        'dateobs': readkey(hdr, 'date-obs'), 'dayobs': readkey(hdr, 'DAY-OBS'), 'filename': path.name,
        'filepath': str(path.parent) + '/', 'filetype': int(filetype),
        'targetid': targetid or find_or_create_target(hdr, conn), 'exptime': readkey(hdr, 'exptime'),
        'filter': readkey(hdr, 'filter'), 'mjd': readkey(hdr, 'mjd'), 'tracknumber': track,
        'telescope': tel, 'airmass': readkey(hdr, 'airmass'), 'objname': readkey(hdr, 'object'),
        'ut': readkey(hdr, 'ut'), 'wcs': readkey(hdr, 'wcserr'), 'instrument': hdr.get('INSTRUME'),
        'ra0': readkey(hdr, 'RA'), 'dec0': readkey(hdr, 'DEC'),
        'lastunpacked': str(datetime.now(timezone.utc).replace(tzinfo=None)),
    }
    if force:
        with (conn or db.connect()):
            (conn or db.connect()).execute('DELETE FROM photlco WHERE filename=?', (path.name,))
    db.insert('photlco', row, conn)
    return True


def run(frames, local_dir=None, nthreads=8, force=False, targetid=None):
    """Place all frames (download or copy) in parallel, then register them serially (one DB writer)."""
    def one(f):
        folder = f.get('_local', local_dir)        # a per-frame source folder (target files) wins
        src = Path(folder) / f['filename'] if folder else None
        if src is not None and not src.exists():
            return None
        return place_frame(f, src)
    with ThreadPoolExecutor(nthreads) as ex:
        paths = [p for p in ex.map(one, frames) if p is not None]
    new = sum(register(p, force=force, targetid=targetid) for p in paths)
    return paths, new
