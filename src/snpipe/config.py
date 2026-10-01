"""Paths and run-wide settings.

The working directory plays the role of the old ``$LCOSNDIR``; the directory layout under it
(``data/lsc/YYYYMMDD``, ``data/0m4/YYYYMMDD``, ``standard/cat/<field>``) is kept identical so
products of the old and new pipelines can be compared file by file.
"""
import os
from importlib.resources import files
from pathlib import Path

PACKAGE_DATA = Path(str(files('snpipe').joinpath('data')))
STANDARD_DIR = PACKAGE_DATA / 'standard'


def workdir():
    """Root of all data and products (``$SNPIPE_DIR``; falls back to ``$LCOSNDIR`` like the old pipeline)."""
    d = os.getenv('SNPIPE_DIR') or os.getenv('LCOSNDIR')
    if not d:
        raise RuntimeError('set SNPIPE_DIR to the pipeline working directory')
    return Path(d)


def db_path():
    return Path(os.getenv('SNPIPE_DB') or workdir() / 'snpipe.sqlite')


def catalog_dir(field):
    """Directory holding catalogs of a given field system (apass, sloan, landolt, gaia)."""
    return workdir() / 'standard' / 'cat' / field


def daydir(telid, instrume, filename):
    """Data directory of a frame, exactly as ``LCOGTingest.download_frame`` (LCOGTingest.py:45-64)."""
    import re
    dayobs = re.search(r'(20\d\d)(0\d|1[0-2])([0-2]\d|3[01])', filename).group()
    if 'fs' in instrume:
        sub = 'data/fts/' + dayobs
    elif instrume == 'en06':
        sub = 'data/floyds/' + dayobs + '_ftn'
    elif instrume in ('en05', 'en12'):
        sub = 'data/floyds/' + dayobs + '_fts'
    elif '1m0' in telid:
        sub = 'data/lsc/' + dayobs
    elif '0m4' in telid:
        sub = 'data/0m4/' + dayobs
    else:
        sub = os.path.join('data', telid, dayobs)
    return workdir() / sub
