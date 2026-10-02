"""SQLite replacement for the old MySQL ``supernova`` database.

Only the tables the reduction stages use are kept (photlco -> ``photlco``, targets, targetnames,
photpairing). Column names, defaults and sentinel values (9999, 'X', quality 127/1) are identical to
``supernova.sql`` so a row of the old and the new pipeline can be compared column by column.
All statements are parameterized and one connection is reused per process.
"""
import os
import sqlite3
import threading

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS photlco (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  targetid INTEGER NOT NULL,
  objname TEXT, dayobs TEXT, dateobs TEXT, ut TEXT, mjd REAL, exptime REAL, filter TEXT,
  telescopeid INTEGER, instrumentid INTEGER, telescope TEXT, instrument TEXT,
  mag REAL DEFAULT 9999, dmag REAL DEFAULT 9999, airmass REAL, wcs REAL,
  psf TEXT DEFAULT 'X', apmag REAL DEFAULT 9999, psfx REAL DEFAULT 9999, psfy REAL DEFAULT 9999,
  psfmag REAL DEFAULT 9999, psfdmag REAL DEFAULT 9999,
  z1 REAL DEFAULT 9999, z2 REAL DEFAULT 9999, zn REAL DEFAULT 9999,
  c1 REAL DEFAULT 9999, c2 REAL DEFAULT 9999, znnum REAL,
  dz1 REAL DEFAULT 9999, dz2 REAL DEFAULT 9999, dzn REAL, dc1 REAL DEFAULT 9999, dc2 REAL DEFAULT 9999,
  zcol1 TEXT, zcol2 TEXT, quality INTEGER DEFAULT 127,
  zcat TEXT DEFAULT 'X', abscat TEXT DEFAULT 'X', fwhm REAL DEFAULT 9999, magtype INTEGER DEFAULT 1,
  ra0 REAL DEFAULT 9999, dec0 REAL DEFAULT 9999, tracknumber INTEGER,
  filename TEXT UNIQUE, difftype INTEGER, filepath TEXT, filetype INTEGER, groupidcode INTEGER,
  datecreated TEXT DEFAULT CURRENT_TIMESTAMP, lastmodified TEXT DEFAULT CURRENT_TIMESTAMP,
  apflux REAL DEFAULT 9999, dapflux REAL DEFAULT 9999, dapmag REAL DEFAULT 9999, limmag REAL,
  lastunpacked TEXT, apercorr REAL
);
CREATE INDEX IF NOT EXISTS photlco_target ON photlco(targetid);
CREATE TABLE IF NOT EXISTS targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ra0 REAL, dec0 REAL, redshift REAL, classification TEXT, classificationid INTEGER,
  sloan_cat TEXT, landolt_cat TEXT, apass_cat TEXT, gaia_cat TEXT,
  pm_ra REAL NOT NULL DEFAULT 0, pm_dec REAL NOT NULL DEFAULT 0,
  groupidcode INTEGER NOT NULL DEFAULT 32769,
  datecreated TEXT DEFAULT CURRENT_TIMESTAMP, lastmodified TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS targetnames (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  targetid INTEGER NOT NULL, name TEXT NOT NULL, groupidcode INTEGER,
  datecreated TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS targetnames_name ON targetnames(name);
CREATE TABLE IF NOT EXISTS photpairing (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  namein TEXT, tablein TEXT, nameout TEXT, tableout TEXT, nametemplate TEXT, tabletemplate TEXT
);
"""

# columns of photlco and their defaults: used to reset a stage (e.g. psf -> 'X') like the old pipeline
SENTINEL = 9999

_local = threading.local()


def connect(path=None):
    """One connection per thread (and per process); rows behave like dicts."""
    path = str(path or config.db_path())
    if getattr(_local, 'pid', None) != os.getpid():
        # forked worker: never reuse the parent's connection (SQLite connections must not cross fork)
        _local.conns, _local.pid = {}, os.getpid()
    conn = _local.conns.get(path)
    if conn is None:
        conn = sqlite3.connect(path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
        _local.conns[path] = conn
    return conn


def query(sql, params=(), conn=None):
    conn = conn or connect()
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update(filename, conn=None, **values):
    """``mysqldef.updatevalue`` equivalent: set columns of the photlco row of ``filename``."""
    if not values:
        return
    conn = conn or connect()
    cols = ', '.join(f'{k}=?' for k in values)
    with conn:
        conn.execute(f'UPDATE photlco SET {cols}, lastmodified=CURRENT_TIMESTAMP WHERE filename=?',
                     (*values.values(), filename))


def insert(table, values, conn=None):
    """Insert a row, dropping missing values like ``mysqldef.insert_values``."""
    missing = ('NaN', 'UNKNOWN', 'N/A', None, '')
    values = {k: v for k, v in values.items() if not (isinstance(v, (str, type(None))) and v in missing)}
    conn = conn or connect()
    cols = ', '.join(values)
    qs = ', '.join('?' * len(values))
    with conn:
        cur = conn.execute(f'INSERT INTO {table} ({cols}) VALUES ({qs})', tuple(values.values()))
    return cur.lastrowid


def get_frame(filename, conn=None):
    rows = query('SELECT * FROM photlco WHERE filename=?', (filename,), conn)
    return rows[0] if rows else None


def target_by_name(name, conn=None):
    """``mysqldef.gettargetid`` by name: ``name like '%<name, spaces->%>'``. Unique match or None."""
    rows = query('SELECT DISTINCT targetid FROM targetnames WHERE name LIKE ?',
                 ('%' + name.replace(' ', '%'),), conn)
    return rows[0]['targetid'] if len(rows) == 1 else None


def target_by_coords(ra, dec, radius=0.01, conn=None):
    """``mysqldef.gettargetid`` by coordinates (default radius 0.01 deg); nearest target or None."""
    import numpy as np
    rows = query('SELECT id, ra0, dec0 FROM targets WHERE dec0 BETWEEN ? AND ?',
                 (dec - radius, dec + radius), conn)
    if not rows:
        return None
    r0, d0 = np.radians([[r['ra0'] for r in rows], [r['dec0'] for r in rows]])
    ra, dec = np.radians([ra, dec])
    hsine = np.sin((d0 - dec) / 2) ** 2 + np.cos(d0) * np.cos(dec) * np.sin((r0 - ra) / 2) ** 2
    dist = np.degrees(2 * np.arcsin(np.sqrt(hsine)))
    i = int(np.argmin(dist))
    return rows[i]['id'] if dist[i] < radius else None


def target_info(targetid, conn=None):
    t = query('SELECT * FROM targets WHERE id=?', (targetid,), conn)[0]
    t['names'] = [r['name'] for r in query('SELECT name FROM targetnames WHERE targetid=?', (targetid,), conn)]
    return t
