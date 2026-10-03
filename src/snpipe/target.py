"""Target files: what a reduction of one object needs to know (``targets/<name>/target.yaml``).

A target file holds the object's identity (name, coordinates), the selection of its input frames (science nights,
reference night) and execution settings (working directory, parallel workers). Every *method* choice is an ASTRA
decision, selected in a universe file next to it (``universes/baseline.yaml``). Schema (docs/guide/targets.md)::

    schema_version: 1
    name: 2025rbs                       # name in the pipeline database
    aliases: [SN2025rbs, SN 2025rbs]    # other names (archive OBJECT spellings)
    ra: 339.265262                      # degrees, where the transient is
    dec: 34.418892
    coordinates: TNS                    # optional: where ra/dec come from
    workdir: ${SNPIPE_WORK}/sn2025rbs   # optional: working directory (else $SNPIPE_DIR, else <target>/work)
    science:
      dayobs: 20250715-20260917         # DAY-OBS range (YYYYMMDD or YYYYMMDD-YYYYMMDD)
      frames: ${SNPIPE_RAW}/2025rbs     # folder with frames.json + the files, or "archive"
    reference:                          # optional; one entry per telescope class (1m0, 0m4, 2m0)
      1m0:
        dayobs: 20260918                # the reference (template) night of that class
        camera: fa                      # camera prefix of the reference frames
        frames: ${SNPIPE_RAW}/2025rbs   # optional, default: science.frames
      # 0m4: {dayobs: ..., camera: sq}  # a class without a reference gets no subtraction
    resources:
      jobs: 8                           # parallel frames for most stages
      diff_jobs: 2                      # parallel frames for subtraction (~7 GB memory each)

A single reference (``reference: {dayobs, camera}``) is accepted and applies to its camera's class.
Science frames are subtracted only with a reference of their own telescope class (the manual: "the best one for
each camera-filter combination"), unless the decision diff_reference_class allows another class.
``templates:`` is accepted as the old name of ``reference:``. Relative paths are relative to the file; ``${VAR}``
is replaced by the environment variable. DAY-OBS is the observing-night label in LCO file names.
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import yaml

SCHEMA_VERSION = 1
KEYS = {'schema_version', 'name', 'aliases', 'ra', 'dec', 'coordinates', 'workdir', 'science', 'reference',
        'templates', 'resources'}
PART_KEYS = {'science': {'dayobs', 'frames'}, 'reference': {'dayobs', 'camera', 'frames', 'survey'}}
SURVEYS = ('ps1', 'sdss')
SURVEY_DAYOBS = '20000101-20991231'   # a survey reference matches any date
CLASSES = ('1m0', '0m4', '2m0')
CAMERA_CLASS = {'fa': '1m0', 'fl': '1m0', 'sq': '0m4', 'ep': '2m0', 'fs': '2m0', 'em': '2m0'}


def frame_class(filename):
    """Telescope class of an LCO frame from its name: cpt1m012-... -> 1m0, elp0m414-... -> 0m4, ogg2m001 -> 2m0."""
    c = filename[3:6]
    return c if c in CLASSES else None
RESOURCE_KEYS = {'jobs', 'diff_jobs'}


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


def _dayobs(where, value):
    """'YYYYMMDD' or 'YYYYMMDD-YYYYMMDD' with real dates in order."""
    value = str(value or '')
    parts = value.split('-')
    try:
        days = [datetime.strptime(p, '%Y%m%d') for p in parts]
    except ValueError:
        days = None
    if not days or len(parts) > 2 or (len(days) == 2 and days[0] > days[1]):
        raise TargetError(f'{where}.dayobs must be YYYYMMDD or YYYYMMDD-YYYYMMDD (first <= last), got {value!r}')
    return value


def _unknown(where, d, allowed):
    extra = set(d) - allowed
    if extra:
        raise TargetError(f'{where}: unknown keys {sorted(extra)} (allowed: {sorted(allowed)})')


def load(path):
    """Read and validate a target file (or a folder containing ``target.yaml``)."""
    path = Path(path)
    if path.is_dir():
        path = path / 'target.yaml'
    if not path.exists():
        raise TargetError(f'no target file {path}')
    t = yaml.safe_load(path.read_text()) or {}
    _unknown(path, t, KEYS)
    if int(t.get('schema_version', SCHEMA_VERSION)) != SCHEMA_VERSION:
        raise TargetError(f'{path}: schema_version {t["schema_version"]} not supported (this snpipe: {SCHEMA_VERSION})')
    for k in ('name', 'ra', 'dec', 'science'):
        if k not in t:
            raise TargetError(f'{path}: missing {k}')
    if 'templates' in t:
        if t.get('reference') is not None:
            raise TargetError(f'{path}: give reference or templates (old name), not both')
        t['reference'] = t.pop('templates')
    t['name'] = str(t['name'])
    t['aliases'] = [str(a) for a in t.get('aliases') or []]
    try:
        ra, dec = float(t['ra']), float(t['dec'])
    except (TypeError, ValueError):
        raise TargetError(f'{path}: ra/dec must be numbers (degrees)')
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise TargetError(f'{path}: ra/dec out of range')
    base = path.parent.resolve()
    sci = dict(t['science'] or {})
    _unknown(f'{path}: science', sci, PART_KEYS['science'])
    sci['dayobs'] = _dayobs(f'{path}: science', sci.get('dayobs'))
    sci['frames'] = _path(base, sci.get('frames', 'archive'))
    t['science'] = sci
    ref = t.get('reference')
    if ref:
        ref = dict(ref)
        if 'survey' in ref and not set(ref) - {'survey'}:
            raise TargetError(f'{path}: a survey reference needs its class, e.g. reference: {{1m0: {{survey: ps1}}}}')
        if set(ref) & PART_KEYS['reference']:          # a single reference: its camera decides the class
            cls = CAMERA_CLASS.get(str(ref.get('camera', '')))
            if cls is None:
                raise TargetError(f"{path}: reference camera {ref.get('camera')!r}: give the class explicitly, "
                                  f"e.g. reference: {{1m0: {{dayobs: ..., camera: ...}}}}")
            ref = {cls: ref}
        _unknown(f'{path}: reference', ref, set(CLASSES))
        lo, _, hi = sci['dayobs'].partition('-')
        for cls, r in list(ref.items()):
            r = dict(r or {})
            where = f'{path}: reference.{cls}'
            _unknown(where, r, PART_KEYS['reference'])
            if r.get('survey'):
                if r['survey'] not in SURVEYS or set(r) - {'survey'}:
                    raise TargetError(f"{where}: survey must be one of {SURVEYS}, alone (got {r})")
                ref[cls] = {'survey': r['survey'], 'camera': r['survey'], 'dayobs': SURVEY_DAYOBS, 'frames': None}
                continue
            r['dayobs'] = _dayobs(where, r.get('dayobs'))
            if not r.get('camera'):
                raise TargetError(f'{where}.camera (e.g. fa, fl, sq) is required')
            r['frames'] = _path(base, r.get('frames')) or sci['frames']
            rlo, _, rhi = r['dayobs'].partition('-')
            if not ((rhi or rlo) < lo or rlo > (hi or lo)):
                raise TargetError(f'{where}: the reference nights overlap the science nights')
            ref[cls] = r
    t['reference'] = ref or None
    res = dict(t.get('resources') or {})
    _unknown(f'{path}: resources', res, RESOURCE_KEYS)
    res = {'jobs': 8, 'diff_jobs': 2, **res}
    if not all(isinstance(v, int) and v > 0 for v in res.values()):
        raise TargetError(f'{path}: resources must be positive integers')
    t['resources'] = res
    t['workdir'] = _path(base, t.get('workdir'))
    t['file'] = path.resolve()
    t['dir'] = base
    return t


def facts(t):
    """What determines the results (for resume signatures): everything except workdir and resources."""
    import hashlib
    plain = lambda v: ({k: plain(x) for k, x in v.items()} if isinstance(v, dict) else
                       [plain(x) for x in v] if isinstance(v, list) else str(v) if isinstance(v, Path) else v)
    keep = ('name', 'aliases', 'ra', 'dec', 'science', 'reference')
    doc = plain({k: v for k, v in t.items() if k in keep})
    lists = []                                       # the frame lists themselves, not only their folders
    for sel in [t['science']] + list((t['reference'] or {}).values()):
        fj = Path(sel['frames']) / 'frames.json' if sel.get('frames') not in (None, 'archive') else None
        lists.append(hashlib.sha256(fj.read_bytes()).hexdigest()[:16] if fj and fj.exists() else '')
    doc['frame_lists'] = lists
    return yaml.safe_dump(doc, sort_keys=True, default_flow_style=True)


def activate(t):
    """Point the pipeline at the target's working directory (unless SNPIPE_DIR is already set)."""
    if not os.getenv('SNPIPE_DIR'):
        wd = t.get('workdir') or t['dir'] / 'work'
        Path(wd).mkdir(parents=True, exist_ok=True)
        os.environ['SNPIPE_DIR'] = str(wd)
    from . import config
    config.workdir().mkdir(parents=True, exist_ok=True)


def dayobs_of(filename):
    m = re.search(r'-(20\d{6})-', filename)
    return m.group(1) if m else None


def in_range(dayobs, rng):
    lo, _, hi = rng.partition('-')
    return dayobs is not None and lo <= dayobs <= (hi or lo)


def frames_for(t, part):
    """Archive frame records of ``part`` ('science' | 'reference'), restricted to its DAY-OBS range(s) and, for the
    reference, to each class's camera. Returns (frames, local folder or None)."""
    if part == 'reference':
        if not t['reference']:
            raise TargetError(f"{t['file']}: no reference section")
        frames = []
        for cls, r in t['reference'].items():
            if r.get('survey'):
                continue                      # made by snpipe.survey, not ingested from frames
            fr, local = _frames(t, r)
            # each class can have its own folder: every record carries where to copy it from (None = download)
            frames += [{**f, '_local': local} for f in fr if frame_class(f['filename']) == cls and r['camera'] in f['filename']]
        return frames, None
    return _frames(t, t['science'])


def _frames(t, sel):
    import json
    src = sel['frames']
    if src == 'archive':
        from . import ingest
        lo, _, hi = sel['dayobs'].partition('-')
        day = lambda d: f'{d[:4]}-{d[4:6]}-{d[6:]}'
        # exposures of a night can carry the next UTC date: query 2 days beyond, then select by DAY-OBS
        end = (datetime.strptime(hi or lo, '%Y%m%d') + timedelta(days=2)).strftime('%Y-%m-%d')
        frames, seen = [], set()
        for obj in [t['name']] + t['aliases']:
            for f in ingest.query_archive(OBJECT=obj, start=day(lo), end=end, RLEVEL=91, configuration_type='EXPOSE'):
                if f['filename'] not in seen:
                    seen.add(f['filename'])
                    frames.append(f)
        local = None
    else:
        fj = Path(src) / 'frames.json'
        if not fj.exists():
            raise TargetError(f'{fj} not found (frames.json = the LCO archive frame records of the files; '
                              'see docs/guide/targets.md)')
        frames, local = json.load(open(fj)), Path(src)
    return [f for f in frames if in_range(dayobs_of(f['filename']), sel['dayobs'])], local
