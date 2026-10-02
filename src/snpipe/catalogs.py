"""Stage ``catalogs``: field-star catalogs for photometric calibration and PSF star selection.

Port of ``comparecatalogs.py`` with the same queries, cuts and file formats, so the zcat stage reads
identical inputs:
* APASS DR9 (VizieR II/336/apass9, box of side 2*radius arcmin, 10.5 < r < 22) — old code shells out to
  the ``vizquery`` CLI (queryapasscat.py); here astroquery.vizier with the same columns;
* SDSS PhotoPrimary stars (type=6, 13 <= r <= 20) via astroquery.sdss (``lscabsphotdef.sloan2file``);
* Pan-STARRS1 DR1 (VizieR II/349) as an SDSS substitute (``panstarrs2file``);
* Gaia DR3 box of 26' (G < 18, astrometric_excess_noise_sig < 2) (``gaia2file``).
Catalog file names are ``<name>_<source>.cat`` in ``standard/cat/<field>/`` and are recorded in the
``targets.<field>_cat`` column ('' = queried, nothing found; NULL = never queried).
"""
import logging

import numpy as np
from astropy import units as u
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table

from . import config, db

log = logging.getLogger(__name__)
FIELDS = ('landolt', 'apass', 'sloan', 'gaia')
_BADCHARS = str.maketrans('', '', ' "*:<>?/|\\')


def apass(ra, dec, radius, output):
    """``queryapasscat.readapass2``: APASS DR9 box query, 10.5 < r' < 22, IRAF-astcat style text file."""
    from astroquery.vizier import Vizier
    cols = ['_RAJ2000', '_DEJ2000', 'Bmag', 'Vmag', "g'mag", "r'mag", "i'mag",
            'e_Vmag', 'e_Bmag', "e_g'mag", "e_r'mag", "e_i'mag"]
    v = Vizier(columns=cols, row_limit=10000)
    res = v.query_region(SkyCoord(ra, dec, unit='deg'), width=2 * radius * u.arcmin, catalog='II/336/apass9')
    if not res:
        return 0
    t = res[0]
    # vizquery -sort=_RA*-c.eq : ascending RA offset from the centre
    t = t[np.argsort(t['_RAJ2000'])]
    def col(name):
        c = t[name]
        return np.ma.filled(np.ma.asarray(c, dtype=float), 9999.)
    mags = {'B': col('Bmag'), 'V': col('Vmag'), 'g': col("g'mag"), 'r': col("r'mag"), 'i': col("i'mag")}
    errs = {'B': col('e_Bmag'), 'V': col('e_Vmag'), 'g': col("e_g'mag"), 'r': col("e_r'mag"), 'i': col("e_i'mag")}
    keep = (mags['r'] < 22) & (mags['r'] > 10.5)
    # vizquery returns sexagesimal, which queryapasscat.deg2HMS converts to DEGREES for the file (header: d degrees);
    # here we start from the same J2000 degrees and write them as degrees
    radec = [(repr(float(r_)), repr(float(d_))) for r_, d_ in
             zip(np.asarray(t['_RAJ2000'], float)[keep], np.asarray(t['_DEJ2000'], float)[keep])]
    filters = ['B', 'V', 'g', 'r', 'i']
    header = '# BEGIN CATALOG HEADER\n# nfields 13\n#     ra     1  0 d degrees %10.5f\n' \
             '#     dec    2  0 d degrees %10.5f\n#     id     3  0 c INDEF %15s\n'
    for n, f in enumerate(filters):
        header += f'#     {f}      {4 + 2 * n} 0 r INDEF %6.2f\n#     {f}err   {5 + 2 * n} 0 r INDEF %6.2f\n'
    header += '# END CATALOG HEADER\n#\n'
    with open(output, 'w') as ff:
        ff.write(header)
        for m, (i, (r_, d_)) in enumerate(zip(np.flatnonzero(keep), radec), start=1):
            ff.write('%14s %14s  %3s  ' % (r_, d_, m))
            for f in filters:
                if mags[f][i] > 0:
                    ff.write(' %6.3f %6.3f  ' % (mags[f][i], errs[f][i]))
                else:
                    ff.write(' %6.3f %6.3f  ' % (9999., 0.0))
            ff.write('\n')
    return int(keep.sum())


def _write_sdsslike(t, output, cols):
    ra, dec, oid = cols[:3]
    t[ra].format, t[dec].format, t[oid].format = '%16.12f', '%16.13f', '%19d'
    names = ['ra', 'dec', 'id', 'u', 'uerr', 'g', 'gerr', 'r', 'rerr', 'i', 'ierr', 'z', 'zerr']
    for c in cols[3:]:
        t[c].format = '%11.9f' if 'err' in c else '%8.5f'
    t.meta['comments'] = ['BEGIN CATALOG HEADER', '   type btext', '   nheader 1', '       csystem J2000',
                          '   nfields 13'] + [
        f'       {n:<5}{i + 1:>2} 0 {"d degrees" if i < 2 else ("c INDEF  " if i == 2 else "r INDEF  ")} {t[c].format}'
        for i, (n, c) in enumerate(zip(names, cols))] + ['END CATALOG HEADER']
    t[cols].write(output, format='ascii.no_header', overwrite=True)


def sloan(ra, dec, radius, output, mag1=13., mag2=20.):
    """``lscabsphotdef.sloan2file``: SDSS PhotoPrimary stars within ``radius`` arcmin."""
    from astroquery.sdss import SDSS
    sql = ("select P.ra, P.dec, P.objID, P.u, P.err_u, P.g, P.err_g, P.r, P.err_r, P.i, P.err_i, P.z, P.err_z "
           "from PhotoPrimary as P, dbo.fGetNearbyObjEq({}, {}, {}) as N "
           "where P.objID=N.objID and P.type=6 and P.r >= {} and P.r <= {}").format(ra, dec, radius, mag1, mag2)
    t = SDSS.query_sql(sql)
    if t is None or len(t) == 0:
        return 0
    _write_sdsslike(t, output, ['ra', 'dec', 'objID'] + [c for f in 'ugriz' for c in (f, 'err_' + f)])
    return len(t)


def panstarrs(ra, dec, radius, output, mag1=13., mag2=20.):
    """``lscabsphotdef.panstarrs2file``: PS1 DR1 stars from VizieR II/349 with the same quality cuts.

    The old code builds its column_filters dict with the key 'rMeanPSFMag' twice, so only the faint
    limit r <= mag2 is applied; that is reproduced here (see docs/bugs.md before changing it).
    """
    from astroquery.vizier import Vizier
    v = Vizier(columns=['raMean', 'decMean', 'objID', 'gFlags', 'yMeanPSFMag', 'yMeanPSFMagErr',
                        'gMeanPSFMag', 'gMeanPSFMagErr', 'rMeanPSFMag', 'rMeanPSFMagErr',
                        'iMeanPSFMag', 'iMeanPSFMagErr', 'zMeanPSFMag', 'zMeanPSFMagErr'],
               column_filters={'nDetections': '>5', 'rMeanPSFMag-rMeanKronMag': '<0.05',
                               'gQfPerfect': '>0.85', 'rQfPerfect': '>0.85', 'iQfPerfect': '>0.85',
                               'zQfPerfect': '>0.85', 'rMeanPSFMag': '<={:f}'.format(mag2)},
               row_limit=-1)
    res = v.query_region(SkyCoord(ra, dec, unit='deg'), radius=radius * u.arcmin, catalog='II/349')
    if not res:
        return 0
    t = res[0]
    good, extended = 8 + 16 + 32 + 256 + 16384 + 32768, 16777216
    t = t[(t['gFlags'] & good == good) & (t['gFlags'] & extended != extended)]
    t.rename_column('ymag', 'umag')
    t.rename_column('e_ymag', 'e_umag')
    t['umag'] = 9999.
    t['e_umag'] = 9999.
    _write_sdsslike(t, output, ['RAJ2000', 'DEJ2000', 'objID'] +
                    [c for f in 'ugriz' for c in (f + 'mag', 'e_' + f + 'mag')])
    return len(t)


def _gaia_vizier(ra, dec, size):
    """Same Gaia DR3 box from the VizieR copy (I/355/gaiadr3) — used when the ESA archive times out."""
    from astroquery.vizier import Vizier
    v = Vizier(columns=['RA_ICRS', 'DE_ICRS', 'Source', 'Gmag', 'sepsi'], row_limit=-1)
    t = v.query_region(SkyCoord(ra, dec, unit='deg'), width=size / np.cos(np.radians(dec)) * u.arcmin,
                       height=size * u.arcmin, catalog='I/355/gaiadr3')[0]
    return Table({'ra': np.asarray(t['RA_ICRS'], float), 'dec': np.asarray(t['DE_ICRS'], float),
                  'source_id': np.asarray(t['Source']), 'phot_g_mean_mag': np.asarray(t['Gmag'], float),
                  'astrometric_excess_noise_sig': np.ma.filled(np.ma.asarray(t['sepsi'], float), np.inf)})


def gaia(ra, dec, output, size=26., mag_limit=18., source='auto'):
    """``lscabsphotdef.gaia2file``: Gaia box of size' x size'/cos(dec), G < 18, excess-noise sig < 2.

    source='esa' uses the ESA archive like the old code; 'vizier' the VizieR copy of the same DR3 table;
    'auto' tries ESA and falls back to VizieR (the ESA archive is unstable ahead of DR4)."""
    r = None
    if source in ('auto', 'esa'):
        try:
            from astroquery.gaia import Gaia
            Gaia.ROW_LIMIT = -1
            Gaia.TIMEOUT = 120
            r = Gaia.query_object_async(coordinate=SkyCoord(ra, dec, unit='deg'),
                                        width=u.Quantity(size / np.cos(np.radians(dec)), u.arcmin),
                                        height=u.Quantity(size, u.arcmin))
            if 'SOURCE_ID' in r.colnames:
                r.rename_column('SOURCE_ID', 'source_id')
        except Exception as e:
            if source == 'esa':
                raise
            log.warning('ESA Gaia archive failed (%s); using VizieR I/355/gaiadr3', e)
    if r is None:
        r = _gaia_vizier(ra, dec, size)
    r = r[(r['phot_g_mean_mag'] < mag_limit) & (r['astrometric_excess_noise_sig'] < 2)]
    r['ra'].format = r['dec'].format = '%16.12f'
    r['phot_g_mean_mag'].format = '%.2f'
    r['ra', 'dec', 'source_id', 'phot_g_mean_mag'].write(output, format='ascii.commented_header',
                                                         delimiter=' ', overwrite=True)
    return len(r)


def read(path):
    """``lscastrodef.readtxt``: read an IRAF-astcat style catalog, naming columns from its header."""
    t = Table.read(path, format='ascii')
    named = False
    for line in t.meta.get('comments', []):
        spec = line.split()
        if spec and spec[0] == 'END':
            break
        if named:
            t.rename_column('col' + spec[1], spec[0])
        if spec and spec[0] == 'nfields':
            named = True
    if 'ra' in t.colnames and t['ra'].dtype.kind in 'US':  # sexagesimal (APASS)
        c = SkyCoord(t['ra'], t['dec'], unit=(u.hourangle, u.deg))
        t['ra'], t['dec'] = c.ra.deg, c.dec.deg
    return t


def run(targetid, fields=FIELDS, radius=20., use_panstarrs=False, force=False, conn=None):
    """Find or download each field catalog of a target; record the file name in ``targets``."""
    t = db.target_info(targetid, conn)
    done = {}
    for field in fields:
        # '' = earlier query found nothing: retry on --force, or for sloan when switching to Pan-STARRS
        retry = t[field + '_cat'] == '' and (force or (field == 'sloan' and use_panstarrs))
        if t[field + '_cat'] is not None and not retry:
            done[field] = t[field + '_cat']
            continue
        source = 'panstarrs' if field == 'sloan' and use_panstarrs else field
        d = config.catalog_dir(field)
        d.mkdir(parents=True, exist_ok=True)
        found = ''
        for name in t['names']:
            fn = name.translate(_BADCHARS) + '_' + source + '.cat'
            if (d / fn).exists():
                found = fn
                break
        if not found and field != 'landolt':
            # comparecatalogs.py queries with the file name of the *last* alias left over from its loop
            fn = t['names'][-1].translate(_BADCHARS) + '_' + source + '.cat'
            try:
                n = {'apass': lambda: apass(t['ra0'], t['dec0'], radius, d / fn),
                     'sloan': lambda: (panstarrs if use_panstarrs else sloan)(t['ra0'], t['dec0'], radius, d / fn),
                     'gaia': lambda: gaia(t['ra0'], t['dec0'], d / fn)}[field]()
                log.info('%s: %s stars -> %s', field, n, fn)
                found = fn if (d / fn).exists() else ''
            except Exception as e:  # network/service failure: record nothing, report
                log.error('%s catalog query failed: %s', field, e)
                done[field] = None
                continue
        with (conn or db.connect()):
            (conn or db.connect()).execute(f'UPDATE targets SET {field}_cat=? WHERE id=?', (found, targetid))
        done[field] = found
    return done
