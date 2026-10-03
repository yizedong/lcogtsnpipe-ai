"""Which frames a stage works on: the old ``lscloop`` selection, optionally filled in from a target file.

Precedence: an option given on the command line wins; otherwise the target file provides it; otherwise the
stage default applies.
"""
from . import db, qa, sites



def cross_class(filename):
    """A difference image made with a reference of another telescope class (``<frame>.optimal.<cam>.diff.fits``
    where <cam>'s class differs from the frame's), e.g. a 0.4-m frame minus a 1-m reference."""
    import re
    from .target import CAMERA_CLASS, frame_class
    m = re.search(r'\.optimal\.([a-z]{2})\.', filename)
    return bool(m) and CAMERA_CLASS.get(m.group(1), frame_class(filename)) != frame_class(filename)


def apply_target(args):
    """Fill -n, -e, --tempdate, --temptel, -T and -j from ``--target-file``. Returns the target (or None)."""
    if not getattr(args, 'target_file', None):
        return None
    from . import target
    t = target.load(args.target_file)
    target.activate(t)
    part = getattr(args, 'frames', None) or 'science'
    if part != 'science' and not t['reference']:
        raise target.TargetError(f"{t['file']}: no reference section, so there are no reference frames")
    if getattr(args, 'name', 'x') is None:
        args.name = t['name']
    if part == 'reference':
        # every class's reference night, only that class's reference camera
        if getattr(args, 'epoch', 'x') is None and getattr(args, 'telescope', 'x') is None:
            args.refsets = [(cls, r['dayobs'], r['camera'], bool(r.get('survey'))) for cls, r in t['reference'].items()]
    elif getattr(args, 'epoch', 'x') is None:
        args.epoch = t['science']['dayobs']
    if args.cmd == 'diff' and getattr(args, 'tempdate', None) in (None, '') and not getattr(args, 'temptel', ''):
        args.references = t['reference'] or {}  # each science frame: the reference of its telescope class
    if getattr(args, 'jobs', 'x') is None:
        args.jobs = t['resources']['diff_jobs' if args.cmd == 'diff' else 'jobs']
    return t


def select_frames(args, conn=None):
    """``myloopdef.get_list`` subset: target, DAY-OBS range, filters, file-name substring, filetype, id, bad stage."""
    sql = 'SELECT p.* FROM photlco p WHERE p.filetype=? '
    params = [args.filetype]
    if getattr(args, 'name', None):
        tid = db.target_by_name(args.name, conn)
        if tid is None:
            raise SystemExit(qa.EXIT['config'])
        sql += 'AND p.targetid=? '
        params.append(tid)
    if getattr(args, 'epoch', None):
        e = args.epoch.split('-')
        sql += 'AND p.dayobs>=? AND p.dayobs<=? '
        params += [e[0], e[-1]]
    if getattr(args, 'refsets', None):
        ors = []
        for cls, rng, cam, survey in args.refsets:
            if survey:                        # survey references: <survey>-<target>-<band>.fits, any class
                ors.append('(p.filename LIKE ?)')
                params.append(f'{cam}-%')
                continue
            e = rng.split('-')
            ors.append('(p.dayobs>=? AND p.dayobs<=? AND substr(p.filename, 4, 3)=? AND p.filename LIKE ?)')
            params += [e[0], e[-1], cls, f'%-{cam}%']
        sql += f"AND ({' OR '.join(ors)}) "
    if getattr(args, 'filter', None):
        fl = []
        for f in args.filter:
            fl += sites.filterst.get(f, [f])
        sql += f"AND p.filter IN ({','.join('?' * len(fl))}) "
        params += fl
    if getattr(args, 'telescope', None):
        sql += 'AND p.filename LIKE ? '
        params.append(f'%{args.telescope}%')
    if getattr(args, 'id', None):
        sql += 'AND p.filename LIKE ? '
        params.append(f'%-{args.id}-%')
    if getattr(args, 'bad', None):
        cond = {'psf': "p.psf='X'", 'zcat': "p.zcat='X'", 'mag': 'p.mag=9999', 'psfmag': 'p.psfmag=9999',
                'wcs': 'p.wcs!=0', 'quality': 'p.quality=1'}[args.bad]
        sql += f'AND {cond} '
    if getattr(args, 'bad', None) != 'quality':
        sql += 'AND p.quality=127 '
    rows = db.query(sql + 'ORDER BY p.mjd', params, conn)
    if getattr(args, 'frames_file', None):
        want = set(open(args.frames_file).read().split())
        return [r for r in rows if r['filename'] in want]
    return [r for r in rows if keep_frame(r['filename'], getattr(args, 'diff_variant', None))]


def keep_frame(name, diff_variant=None):
    """A difference image is selected when its variant tag (.cut = region cutout, .fit = PyZOGY gain fit; .zp = an
    old test) is the run's choice (--diff-variant gain:region:reference_class, passed by the recipe from the
    universe) and, unless the choice allows it, its reference is of the frame's own telescope class."""
    if '.diff.' not in name:
        return True
    gain, region, refclass = (diff_variant or 'zeropoint:full:same').split(':')
    want = ('.cut' if region == 'cutout' else '') + ('.fit' if gain == 'fit' else '')
    tag = ''.join(t for t in ('.cut', '.fit', '.zp') if t + '.' in name)
    return tag == want and (refclass == 'any' or not cross_class(name))
