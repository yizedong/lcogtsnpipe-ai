"""Which frames a stage works on: the old ``lscloop`` selection, optionally filled in from a target file.

Precedence: an option given on the command line wins; otherwise the target file provides it; otherwise the
stage default applies.
"""
from . import db, qa, sites

# products of non-default diff options (.fit = --gain fit, .cut = --region cutout; .zp = zero-point gain when it
# was still a test option) are variants: selected only when listed in --frames-file, never twice in a light curve
TEST_PRODUCTS = ('.fit.diff', '.zp.diff', '.cut.diff', '.cut.zp.diff', '.cut.fit.diff')


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
            args.refsets = [(cls, r['dayobs'], r['camera']) for cls, r in t['reference'].items()]
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
        for cls, rng, cam in args.refsets:
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
    return [r for r in rows if not any(t in r['filename'] for t in TEST_PRODUCTS)]
