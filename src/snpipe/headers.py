"""FITS header access with the instrument-dependent keyword map of ``lsc.util.readkey3`` (util.py:144-339)."""
import re

from astropy import units as u
from astropy.coordinates import Angle
from astropy.io import fits

MISSING = ('NaN', 'UNKNOWN', None, '', 'UNSPECIFIED', 'N/A')

_LCO = {
    'object': 'OBJECT', 'date-obs': 'DATE-OBS', 'ut': 'DATE-OBS', 'date-night': 'DAY-OBS',
    'RA': 'RA', 'DEC': 'DEC', 'CAT-RA': 'CAT-RA', 'CAT-DEC': 'CAT-DEC',
    'datamin': -100.0, 'datamax': 'SATURATE', 'observer': 'OBSERVER', 'exptime': 'EXPTIME',
    'wcserr': 'WCSERR', 'instrume': 'INSTRUME', 'JD': 'MJD-OBS', 'mjd': 'MJD-OBS', 'filter': 'FILTER',
    'gain': 'GAIN', 'ron': 'RDNOISE', 'airmass': 'AIRMASS', 'type': 'OBSTYPE', 'propid': 'PROPID',
    'userid': 'USERID', 'telescop': 'TELESCOP',
}
_EXTERNAL = {  # SDSS/PS1/other templates
    'object': 'OBJECT', 'RA': 'RA', 'DEC': 'DEC', 'CAT-RA': 'RA', 'CAT-DEC': 'DEC', 'ron': 'RDNOISE',
    'mjd': 'MJD-OBS', 'ut': 'DATE-OBS', 'date-obs': 'DATE-OBS', 'date-night': 'DAY-OBS', 'datamax': 'SATURATE',
}


def _keymap(hdr):
    inst = str(hdr.get('INSTRUME') or 'none').lower()
    if any(k in inst for k in ('kb', 'sq', 'fl', 'fa', 'ep')):
        return _LCO
    if 'fs' in inst or 'em' in inst:
        keys = dict(_LCO)
        if str(hdr.get('DATE-OBS')) < '2014-04-01':  # old Spectral headers
            keys.update({'datamax': 60000.0, 'wcserr': 'WCS_ERR', 'JD': 'MJD', 'mjd': 'MJD', 'telescop': 'TELID',
                         'ron': next((k for k in ('RDNOISE', 'READNOIS') if k in hdr), 'ron')})
            if inst == 'fs02':
                keys['pixscale'] = 0.30104
            elif inst in ('fs01', 'fs03'):
                keys['pixscale'] = 0.304
        return keys
    return _EXTERNAL


def readkey(hdr, keyword):
    """Value of a logical keyword, converted like ``readkey3`` (dates, UT, RA/Dec in degrees, filter fallback)."""
    keys = _keymap(hdr)
    if keyword in keys:
        k = keys[keyword]
        if isinstance(k, float):
            value = k
        else:
            value = hdr.get(k)
            if keyword == 'date-obs':
                try:
                    value = value.split('T')[0].replace('-', '')
                except AttributeError:
                    pass
            elif keyword == 'ut':
                value = value.split('T')[1] if 'T' in value else (value.split()[1] if ' ' in value else '')
            elif keyword == 'object':
                value = re.sub(r'[()\[\]{}]', '', value)
            elif keyword == 'JD':
                value = value + 0.5
            elif keyword == 'instrume':
                value = value.lower()
            elif keyword == 'filter' and value in (None, 'air'):
                for key in ('FILTER2', 'FILTER1', 'FILTER3'):
                    if hdr.get(key) not in (None, 'air'):
                        value = hdr[key]
                        break
            elif keyword in ('RA', 'CAT-RA') and isinstance(value, str) and ':' in value:
                value = Angle(value, u.hourangle).deg
            elif keyword in ('RA', 'CAT-RA', 'DEC', 'CAT-DEC') and value not in MISSING:
                value = Angle(value, u.deg).deg
    elif keyword in hdr:
        value = hdr.get(keyword)
    else:
        value = ''
    if isinstance(value, str):
        value = value.replace('\\#', '')
    if value == 'ftn':
        value = '2m0-01'
    elif value == 'fts':
        value = '2m0-02'
    return value


def read_image(path):
    """(data, header) of the science extension; works for funpacked ``.fits`` and BANZAI ``.fits.fz``."""
    with fits.open(path) as hdul:
        hdu = hdul['SCI'] if 'SCI' in hdul else next(h for h in hdul if h.data is not None and h.data.ndim == 2)
        return hdu.data.astype('float32'), hdu.header.copy()


def read_header(path):
    with fits.open(path) as hdul:
        hdu = hdul['SCI'] if 'SCI' in hdul else (hdul[1] if str(path).endswith('.fz') else hdul[0])
        return hdu.header.copy()
