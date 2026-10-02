"""Target files: the facts about one object that a reduction needs (``targets/<name>/target.yaml``).

A target file holds only facts — where the object is, which nights are science and which are the reference
(template), where the frames are. Every *choice* about how to reduce them is an ASTRA decision, selected in a
universe file next to it (``targets/<name>/universes/baseline.yaml``). Example (all keys documented in
docs/guide/targets.md)::

    name: 2025rbs                       # name in the pipeline database (used by every stage as -n)
    aliases: [SN2025rbs, SN 2025rbs]    # other names (archive OBJECT spellings)
    ra: 339.265262                      # degrees (TNS)
    dec: 34.418892
    workdir: ../../work/sn2025rbs       # optional: pipeline working directory (else $SNPIPE_DIR)
    science:
      dayobs: 20250715-20260917         # DAY-OBS range to reduce (YYYYMMDD-YYYYMMDD)
      frames: /data/rawdata/2025rbs     # folder with frames.json + the files, or "archive"
    templates:
      dayobs: 20260918                  # DAY-OBS of the reference night (one night or a range)
      camera: fa                        # camera prefix of the reference frames (fa, fl, sq, ...)
      frames: /data/rawdata/2025rbs     # optional, default: same as science
    resources:
      jobs: 8                           # parallel frames for most stages
      diff_jobs: 2                      # parallel frames for diff (~7 GB of memory each)

Relative paths are relative to the target file. DAY-OBS is the LCO observing-night label in the file name
(``...-20260918-...``), which can differ from the UTC date of the exposure.
"""
import os
import re
from pathlib import Path

import yaml

REQUIRED = ('name', 'ra', 'dec', 'science', 'templates')
DAYOBS = re.compile(r'^20\d{6}(-20\d{6})?$')


class TargetError(ValueError):
    pass


def _path(base, value):
    if value is None or value == 'archive':
        return value
    v = os.path.expandvars(str(value))
    if '$' in v:
        raise TargetError(f'{value}: environment variable not set (e.g. export SNPIPE_RAW=/path/to/raw/frames)')
    p = Path(v).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load(path):
    """Read and validate a target file (or a target directory containing ``target.yaml``)."""
    path = Path(path)
    if path.is_dir():
        path = path / 'target.yaml'
    if not path.exists():
        raise TargetError(f'no target file {path}')
    t = yaml.safe_load(path.read_text()) or {}
    missing = [k for k in REQUIRED if k not in t]
    if missing:
        raise TargetError(f'{path}: missing {missing}')
    t['name'] = str(t['name'])
    t['aliases'] = [str(a) for a in t.get('aliases') or []]
    if not (0 <= float(t['ra']) < 360 and -90 <= float(t['dec']) <= 90):
        raise TargetError(f'{path}: ra/dec out of range')
    for part in ('science', 'templates'):
        d = t[part] = dict(t[part] or {})
        d['dayobs'] = str(d.get('dayobs', ''))
        if not DAYOBS.match(d['dayobs']):
            raise TargetError(f'{path}: {part}.dayobs must be YYYYMMDD or YYYYMMDD-YYYYMMDD, got {d["dayobs"]!r}')
    if not t['templates'].get('camera'):
        raise TargetError(f'{path}: templates.camera (e.g. fa, fl, sq) is required')
    base = path.parent.resolve()
    t['science']['frames'] = _path(base, t['science'].get('frames', 'archive'))
    t['templates']['frames'] = _path(base, t['templates'].get('frames')) or t['science']['frames']
    t['workdir'] = _path(base, t.get('workdir'))
    t['resources'] = {'jobs': 8, 'diff_jobs': 2, **(t.get('resources') or {})}
    t['file'] = path.resolve()
    t['dir'] = base
    return t


def activate(t):
    """Point the pipeline at the target's working directory (unless SNPIPE_DIR is already set)."""
    if t.get('workdir') and not os.getenv('SNPIPE_DIR'):
        Path(t['workdir']).mkdir(parents=True, exist_ok=True)
        os.environ['SNPIPE_DIR'] = str(t['workdir'])
    from . import config
    config.workdir().mkdir(parents=True, exist_ok=True)


def dayobs_of(filename):
    m = re.search(r'-(20\d{6})-', filename)
    return m.group(1) if m else None


def in_range(dayobs, rng):
    lo, _, hi = rng.partition('-')
    return dayobs is not None and lo <= dayobs <= (hi or lo)


def frames_for(t, part):
    """Frame list (archive records) of ``part`` = 'science' | 'templates', restricted to its DAY-OBS range."""
    import json
    sel = t[part]
    src = sel['frames']
    if src == 'archive':
        from . import ingest
        lo, _, hi = sel['dayobs'].partition('-')
        hi = hi or lo
        day = lambda d: f'{d[:4]}-{d[4:6]}-{d[6:]}'
        frames = []
        for obj in [t['name']] + t['aliases']:
            frames += ingest.query_archive(OBJECT=obj, start=day(lo), end=day(str(int(hi) + 2)),
                                           RLEVEL=91, configuration_type='EXPOSE')
        seen, uniq = set(), []
        for f in frames:
            if f['filename'] not in seen:
                seen.add(f['filename'])
                uniq.append(f)
        frames, local = uniq, None
    else:
        fj = Path(src) / 'frames.json'
        if not fj.exists():
            raise TargetError(f'{fj} not found (frames.json = the LCO archive frame records of the files; '
                              'see docs/guide/targets.md)')
        frames, local = json.load(open(fj)), Path(src)
    frames = [f for f in frames if in_range(dayobs_of(f['filename']), sel['dayobs'])]
    return frames, local
