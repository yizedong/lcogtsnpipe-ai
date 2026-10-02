"""``snpipe`` command line.

Whole reductions (docs/guide/running.md):
    snpipe init-target targets/sn2025xyz --name 2025xyz --ra .. --dec .. --science 20250801-20251231 \
        --templates 20260901 --camera fa --frames /data/2025xyz
    snpipe run targets/sn2025xyz [--universe baseline] [--from STEP] [--only STEP] [--dry-run]
    snpipe status targets/sn2025xyz

One stage at a time (what the recipe pipeline/astra.yaml runs; lscloop-like frame selection):
    snpipe psf --target-file targets/sn2025xyz [--frames templates] [--filetype 4] [-f B V] [-j 8]
    snpipe psf -n 2025xyz -e 20250801-20251231          (without a target file)
Every stage prints a JSON summary, writes per-frame QA files and exits 0 ok, 1 some frames failed their
checks, 2 configuration error, 3 missing input, 4 external service failed.
"""
import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from . import db, qa, sites

log = logging.getLogger('snpipe')
QA_OUT = None   # --qa-out: also write this call's stage summary here (the ASTRA output of a recipe)


def apply_target_file(args):
    """``--target-file``: fill -n / -e / --tempdate / --temptel / -j from the target's facts (explicit options win).
    ``--frames science`` selects the science nights, ``--frames templates`` the reference night."""
    tf = getattr(args, 'target_file', None)
    if not tf:
        return None
    from . import target
    t = target.load(tf)
    target.activate(t)
    if getattr(args, 'name', 'x') is None:
        args.name = t['name']
    part = getattr(args, 'frames', None) or 'science'
    if getattr(args, 'epoch', 'x') is None:
        args.epoch = t[part]['dayobs']
    if getattr(args, 'tempdate', 'x') in (None, ''):
        args.tempdate = t['templates']['dayobs']
    if getattr(args, 'temptel', 'x') in (None, ''):
        args.temptel = t['templates']['camera']
    if getattr(args, 'jobs', 'x') is None:
        args.jobs = t['resources']['diff_jobs' if args.cmd == 'diff' else 'jobs']
    if part == 'templates' and getattr(args, 'telescope', 'x') is None:
        args.telescope = t['templates']['camera']   # only the reference camera's frames of that night
    return t


def select_frames(args, conn=None):
    """``myloopdef.get_list`` subset: target, epoch, filters, telescope, filetype, id, bad-stage."""
    sql = ('SELECT p.* FROM photlco p WHERE p.filetype=? ')
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
    sql += 'ORDER BY p.mjd'
    rows = db.query(sql, params, conn)
    if getattr(args, 'frames_file', None):
        want = set(open(args.frames_file).read().split())
        rows = [r for r in rows if r['filename'] in want]
    else:
        # products of non-default diff options (.zp = --gain zeropoint, .cut = --region cutout) are tests: only
        # selected when listed in --frames-file, so they never enter a default light curve twice
        rows = [r for r in rows if not any(t in r['filename'] for t in ('.zp.diff', '.cut.diff', '.cut.zp.diff'))]
    return rows


def _whole(args):
    from . import run, target
    try:
        if args.cmd == 'init-target':
            f = run.init_target(args.target_dir, args.name, args.ra, args.dec, args.science, args.templates,
                                args.camera, args.frames, args.alias, args.workdir)
            print(json.dumps({'target_file': str(f)}))
            return 0
        if args.cmd == 'status':
            s = run.status(args.target_dir, args.universe)
            if s is None:
                print(json.dumps({'status': 'not run'}))
                return 0
            print(f"{s['target']} / {s['universe']}  workdir {s['workdir']}  commit {s['code'].get('commit', '?')[:10]}")
            for sid, st in s['steps'].items():
                print(f"  {sid:28s} {st.get('status', ''):15s} exit {st.get('exit', ''):>2}  {st.get('seconds', '')} s")
            return 0
        if args.sbatch:
            print(run.sbatch_script(args.target_dir, args.universe))
            return 0
        summary, rc = run.run(args.target_dir, args.universe, only=args.only, start=args.start,
                              dry_run=args.dry_run, keep_going=args.keep_going, analysis=args.recipe)
        print(json.dumps(summary, indent=1))
        return rc
    except target.TargetError as e:
        print(json.dumps({'error': str(e)}))
        return qa.EXIT['config']


def _write_json(path, obj):
    if path:
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(obj, indent=1, default=str))


def _safe(fn, frame, stage, **kw):
    """One frame's failure must not stop the stage: exceptions become a 'fail' FrameQA."""
    import traceback
    try:
        return fn(frame, **kw)
    except Exception as e:
        q = qa.FrameQA(frame, stage)
        q.fail(f'{type(e).__name__}: {e}')
        q.metrics['traceback'] = traceback.format_exc(limit=3)
        return q


def _write_qa(r):
    """Per-frame QA as soon as the frame is done; a 'skipped' result never overwrites earlier QA."""
    from pathlib import Path
    row = db.get_frame(r.frame)
    if not row:
        return
    path = Path(row['filepath']) / r.frame
    out = Path(str(path).replace('.fits', f'.{r.stage}.qa.json'))
    if r.status == 'skipped' and out.exists():
        return
    qa.write_frame(r, path)


def _run_stage(stage, frames, jobs, fn, **kw):
    from concurrent.futures import as_completed
    started = time.strftime('%Y-%m-%dT%H:%M:%S')
    results = []
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            futs = {ex.submit(_safe, fn, f, stage, **kw): f for f in frames}
            for fut in as_completed(futs):
                r = fut.result()
                _write_qa(r)
                results.append(r)
    else:
        for f in frames:
            r = _safe(fn, f, stage, **kw)
            _write_qa(r)
            results.append(r)
    s = qa.write_summary(stage, results, params=kw, started=started, out=QA_OUT)
    print(json.dumps({k: s[k] for k in ('stage', 'status', 'counts', 'n_frames', 'wall_seconds')}))
    return qa.exit_code(s)


def _cosmic(frame, force=False):
    from pathlib import Path
    from . import cosmic
    row = db.get_frame(frame)
    return cosmic.run_one(Path(row['filepath']) / frame, force=force)


def _redo_params(stage, frame):
    from . import config
    f = config.workdir() / 'review' / 'redo_params.json'
    return json.loads(f.read_text()).get(stage, {}).get(frame, {}) if f.exists() else {}


def _psf(frame, **kw):
    from . import psf
    extra = _redo_params('psf', frame)  # remediation knobs left by a reviewer's 'redo' verdict
    if extra:
        kw = {**kw, **extra, 'redo': True}
    return psf.run_one(frame, **kw)


def _psfmag(frame, **kw):
    from . import psfmag
    return psfmag.run_one(frame, **kw)


def _wcs(frame, **kw):
    from . import wcs
    return wcs.run_one(frame, **kw)


def _template(frame, **kw):
    from . import template
    return template.run_one(frame, **kw)


def _diff(frame, **kw):
    from . import diff
    return diff.run_one(frame, **kw)


def _zcat(frame, **kw):
    from . import zcat
    return zcat.run_one(frame, **kw)


def main(argv=None):
    p = argparse.ArgumentParser(prog='snpipe')
    p.add_argument('-v', '--verbose', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('add-target')
    a.add_argument('name', nargs='?')
    a.add_argument('--target-file', help='target.yaml: name, coordinates and aliases from the file')
    a.add_argument('--ra', type=float)
    a.add_argument('--dec', type=float)
    a.add_argument('--alias', nargs='*', default=[])
    a.add_argument('--qa-out', help='also write the result JSON here')

    a = sub.add_parser('ingest')
    a.add_argument('--target-file', help='target.yaml: ingest its science or template frames (see --frames)')
    a.add_argument('--frames', choices=['science', 'templates'], default='science')
    a.add_argument('--target', help='archive OBJECT name (without --target-file)')
    a.add_argument('--start')
    a.add_argument('--end')
    a.add_argument('--filters', nargs='*')
    a.add_argument('--tels', nargs='*', help='1m0 0m4 2m0')
    a.add_argument('--frames-json', help='use a saved archive frame list instead of querying')
    a.add_argument('--local-dir', help='copy files from here instead of downloading')
    a.add_argument('-j', '--jobs', type=int, default=8)
    a.add_argument('--qa-out', help='also write the result JSON here')

    a = sub.add_parser('run', help='run the whole recipe (pipeline/astra.yaml) for a target folder')
    a.add_argument('target_dir')
    a.add_argument('--universe', default='baseline')
    a.add_argument('--from', dest='start', help='rerun this step and every step after it')
    a.add_argument('--only', help='run only this step')
    a.add_argument('--dry-run', action='store_true', help='print the commands without running them')
    a.add_argument('--keep-going', action='store_true', help='after a stopped step, still run independent steps')
    a.add_argument('--recipe', help='another astra.yaml (default: the packaged pipeline/astra.yaml)')
    a.add_argument('--sbatch', action='store_true', help='print a SLURM job script for this run instead')

    a = sub.add_parser('status', help='what ran for a target, with status and time per step')
    a.add_argument('target_dir')
    a.add_argument('--universe', default='baseline')

    a = sub.add_parser('init-target', help='create targets/<name>/target.yaml + universes/baseline.yaml')
    a.add_argument('target_dir')
    a.add_argument('--name', required=True)
    a.add_argument('--ra', type=float, required=True)
    a.add_argument('--dec', type=float, required=True)
    a.add_argument('--alias', nargs='*', default=[])
    a.add_argument('--science', required=True, help='DAY-OBS range YYYYMMDD-YYYYMMDD')
    a.add_argument('--templates', required=True, help='DAY-OBS of the reference night')
    a.add_argument('--camera', required=True, help='camera prefix of the reference frames (fa, fl, sq, ...)')
    a.add_argument('--frames', default='archive', help='folder with frames.json + the files, or archive')
    a.add_argument('--workdir')

    a = sub.add_parser('report', help='write the standard report of a run (report.md + figures)')
    a.add_argument('--target-file')
    a.add_argument('-o', '--output', required=True, help='results/<universe>/report.md')

    a = sub.add_parser('review-all', help='review queues for every step of a run')
    a.add_argument('--target-file')
    a.add_argument('--sample', type=int, default=5)
    a.add_argument('-o', '--output', required=True, help='results/<universe>/review_queue.json')

    a = sub.add_parser('review', help='build review packets/queue for a stage')
    a.add_argument('stage')
    a.add_argument('--frame')
    a.add_argument('--sample', type=int, default=5)
    a.add_argument('--ensemble', nargs='*', help='metrics to compare against peer frames')

    a = sub.add_parser('verdict', help='record a review verdict (agent or human)')
    a.add_argument('frame')
    a.add_argument('stage')
    a.add_argument('verdict', choices=['accept', 'redo', 'bad', 'delete', 'ulim'])
    a.add_argument('--reason', required=True)
    a.add_argument('--param', nargs='*', default=[], help='k=v remediation knobs for redo')
    a.add_argument('--who', default='agent')

    a = sub.add_parser('catalogs')
    a.add_argument('--target-file')
    a.add_argument('--target')
    a.add_argument('--fields', nargs='*', default=['landolt', 'apass', 'sloan', 'gaia'])
    a.add_argument('--panstarrs', action='store_true')
    a.add_argument('--sloan-source', choices=['sdss', 'panstarrs'], default='sdss')
    a.add_argument('-F', '--force', action='store_true')
    a.add_argument('-o', '--output', help='also write the result JSON here')

    for stage in ('wcs', 'cosmic', 'psf', 'psfmag', 'zcat', 'template', 'diff', 'mag', 'getmag'):
        a = sub.add_parser(stage)
        a.add_argument('--target-file', help='target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j')
        a.add_argument('--frames', choices=['science', 'templates'], default='science',
                       help='with --target-file: which nights -e selects')
        a.add_argument('--qa-out', help='also write the stage summary JSON here')
        a.add_argument('-n', '--name')
        a.add_argument('-e', '--epoch')
        a.add_argument('-f', '--filter', nargs='+')
        a.add_argument('-T', '--telescope')
        a.add_argument('-d', '--id')
        a.add_argument('-b', '--bad')
        a.add_argument('--filetype', type=int, default=1)
        a.add_argument('--frames-file', help='restrict to the frame names listed in this file')
        a.add_argument('-F', '--force', action='store_true')
        a.add_argument('-j', '--jobs', type=int, default=None, help='parallel frames (default 8, diff 2)')
        if stage == 'psf':
            a.add_argument('--fwhm', type=float)
            a.add_argument('--nstars', type=lambda v: int(str(v).lstrip('n')), default=6,
                           help='number of PSF stars (also accepts the ASTRA option ids n6, n12, n20)')
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float, default=-100.)
            a.add_argument('--max-apercorr', type=lambda v: float(str(v).replace('apco_', '').replace('p', '.')),
                           default=0.1, help='mag (also accepts the ASTRA option ids apco_0p1, apco_0p2)')
            a.add_argument('--field', default='gaia')
            a.add_argument('--model', choices=['daophot', 'epsf'], default='daophot')
            a.add_argument('--no-auto-fix', action='store_true', help='do not run the remediation ladder')
            a.add_argument('--auto-fix', choices=['ladder', 'off'], default='ladder')
        if stage == 'psfmag':
            order = lambda v: int(str(v).replace('order', ''))   # also accepts the ASTRA option ids order1, order3
            a.add_argument('-x', '--xord', type=order, default=3)
            a.add_argument('-y', '--yord', type=order, default=3)
            a.add_argument('--bkg', type=float, default=4.)
            a.add_argument('--size', type=float, default=7.)
            a.add_argument('-c', '--no-recenter', action='store_true')
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float)
            a.add_argument('--RA', type=float)
            a.add_argument('--DEC', type=float)
        if stage == 'diff':
            a.add_argument('--tempdate', default=None, help='DAY-OBS (range) of the reference frames')
            a.add_argument('--temptel', default='', help='camera prefix of the reference frames (fa, fl, sq...)')
            a.add_argument('--normalize', choices=['t', 'i'], default='t')
            a.add_argument('--unmask', action='store_true')
            a.add_argument('--register', default='adaptive', help='adaptive | exact | bilinear | bicubic')
            a.add_argument('--region', choices=['full', 'cutout'], default='full')
            a.add_argument('--gain', choices=['fit', 'zeropoint'], default='fit',
                           help='PyZOGY flux ratio: iterative fit (old default) or from zcat zero points')
            a.add_argument('--cutout-size', type=int, default=2048)
        if stage in ('mag', 'getmag'):
            a.add_argument('--type', choices=['fit', 'ph', 'mag'], default=None)
            a.add_argument('--match-by-site', action='store_true')
            a.add_argument('-o', '--output')
            a.add_argument('--combine', type=float, default=1e-10)
            if stage == 'getmag':
                a.add_argument('--keep-failed', action='store_true',
                               help='keep points whose mag/diff QA failed (dropped by default)')
        if stage == 'zcat':
            a.add_argument('--field', default='')
            a.add_argument('--catalogue', default='')
            a.add_argument('--unfix', action='store_true')
            a.add_argument('--type', choices=['fit', 'ph'], default='fit')
            a.add_argument('--sigma-clip', type=float, default=2.)
            a.add_argument('--match-by-site', action='store_true')

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')

    if args.cmd in ('run', 'status', 'init-target'):
        return _whole(args)

    global QA_OUT
    QA_OUT = getattr(args, 'qa_out', None)
    t = apply_target_file(args) if args.cmd not in ('add-target', 'ingest', 'catalogs', 'report', 'review-all') else None
    if getattr(args, 'target_file', None) and t is None:
        from . import target
        t = target.load(args.target_file)
        target.activate(t)
    if args.cmd in ('wcs', 'cosmic', 'psf', 'psfmag', 'zcat', 'template', 'diff', 'mag', 'getmag') and args.jobs is None:
        args.jobs = 2 if args.cmd == 'diff' else 8
    if args.cmd == 'diff' and args.tempdate is None:
        print(json.dumps({'stage': 'diff', 'status': 'fail', 'error': 'give --tempdate or --target-file'}))
        return qa.EXIT['config']

    if args.cmd == 'add-target':
        from . import ingest
        if t:
            args.name, args.ra, args.dec, args.alias = t['name'], float(t['ra']), float(t['dec']), t['aliases']
        if args.name is None or args.ra is None or args.dec is None:
            print(json.dumps({'error': 'give NAME --ra --dec, or --target-file'}))
            return qa.EXIT['config']
        tid = ingest.add_target(args.name, args.ra, args.dec)
        for al in args.alias:
            if db.target_by_name(al) is None:
                db.insert('targetnames', {'name': al, 'targetid': tid, 'groupidcode': 32769})
        res = {'targetid': tid, 'name': args.name, 'ra': args.ra, 'dec': args.dec, 'aliases': args.alias}
        print(json.dumps(res))
        if t:
            _write_json(QA_OUT, res)
        return 0
    if args.cmd == 'ingest' and t:
        from . import ingest, target
        tid = db.target_by_name(t['name'])
        if tid is None:
            print(json.dumps({'error': f"target {t['name']} not in the database: run add-target first"}))
            return qa.EXIT['config']
        frames, local = target.frames_for(t, args.frames)
        frames = [f for f in frames if (not args.filters or f['primary_optical_element'] in args.filters)
                  and (not args.tels or f['TELID'][:3] in args.tels)]
        paths, new = ingest.run(frames, local, args.jobs, targetid=tid)
        placed = {p.name for p in paths}
        missing = sorted(f['filename'] for f in frames if f['filename'].replace('.fz', '') not in placed)
        res = {'part': args.frames, 'dayobs': t[args.frames]['dayobs'], 'frames': len(frames),
               'placed': len(paths), 'new_rows': new, 'missing': missing[:50]}
        print(json.dumps(res))
        _write_json(args.qa_out, res)
        if not frames:
            return qa.EXIT['missing_input']
        return qa.EXIT['ok'] if len(paths) == len(frames) else qa.EXIT['missing_input']
    if args.cmd == 'ingest':
        from . import ingest
        if not args.target:
            print(json.dumps({'error': 'give --target or --target-file'}))
            return qa.EXIT['config']
        if args.frames_json:
            frames = json.load(open(args.frames_json))
        else:
            frames = ingest.query_archive(OBJECT=args.target, start=args.start, end=args.end,
                                          RLEVEL=91, configuration_type='EXPOSE')
        frames = [f for f in frames if (not args.filters or f['primary_optical_element'] in args.filters)
                  and (not args.tels or f['TELID'][:3] in args.tels)]
        paths, new = ingest.run(frames, args.local_dir, args.jobs)
        print(json.dumps({'frames': len(frames), 'placed': len(paths), 'new_rows': new}))
        return qa.EXIT['ok'] if len(paths) == len(frames) else qa.EXIT['missing_input']
    if args.cmd == 'catalogs':
        from . import catalogs
        tid = db.target_by_name(t['name'] if t else args.target)
        if tid is None:
            print(json.dumps({'error': 'unknown target: run add-target first'}))
            return qa.EXIT['config']
        res = catalogs.run(tid, args.fields, use_panstarrs=args.panstarrs or args.sloan_source == 'panstarrs',
                           force=args.force)
        print(json.dumps(res))
        _write_json(args.output, res)
        return qa.EXIT['external'] if any(v is None for v in res.values()) else 0

    if args.cmd == 'report':
        from . import report
        print(json.dumps({'report': str(report.write(args.output, args.target_file))}))
        return 0
    if args.cmd == 'review-all':
        from . import report
        q = report.review_all(args.output, args.sample)
        print(json.dumps({k: v.get('n_items', v.get('error')) for k, v in q.items()}))
        return 0
    if args.cmd == 'review':
        from . import review
        if args.frame:
            print(review.packet(args.stage, args.frame))
            return 0
        if args.ensemble:
            print(json.dumps(review.ensemble(args.stage, args.ensemble), indent=1))
        print(review.queue(args.stage, args.sample))
        return 0
    if args.cmd == 'verdict':
        from . import review
        params = {}
        for kv in args.param:
            k, v = kv.split('=', 1)
            try:
                v = json.loads(v)
            except ValueError:
                pass
            params[k] = v
        print(json.dumps(review.verdict(args.frame, args.stage, args.verdict, args.reason, params, args.who)))
        return 0

    frames = [r['filename'] for r in select_frames(args)]
    if not frames:
        res = {'stage': args.cmd, 'status': 'skipped', 'n_frames': 0,
               'message': 'no frames selected (check -n/-e/--filetype, or run the earlier stages)'}
        print(json.dumps(res))
        _write_json(QA_OUT, res)
        return qa.EXIT['missing_input']
    if args.cmd == 'wcs':
        return _run_stage('wcs', frames, args.jobs, _wcs, force=args.force)
    if args.cmd == 'cosmic':
        return _run_stage('cosmic', frames, args.jobs, _cosmic, force=args.force)
    if args.cmd == 'psf':
        return _run_stage('psf', frames, args.jobs, _psf, redo=args.force, fwhm=args.fwhm, nstars=args.nstars,
                          datamax=args.datamax, datamin=args.datamin, max_apercorr=args.max_apercorr,
                          field=args.field, model=args.model,
                          auto_fix=not args.no_auto_fix and args.auto_fix == 'ladder')
    if args.cmd == 'psfmag':
        return _run_stage('psfmag', frames, args.jobs, _psfmag, redo=args.force, xord=args.xord, yord=args.yord,
                          bkg=args.bkg, size=args.size, recenter=not args.no_recenter, datamax=args.datamax,
                          datamin=args.datamin, ra=args.RA, dec=args.DEC)
    if args.cmd == 'template':
        return _run_stage('template', frames, 1, _template, force=args.force)
    if args.cmd == 'diff':
        return _run_stage('diff', frames, args.jobs, _diff, tempdate=args.tempdate, temptel=args.temptel,
                          normalize=args.normalize, unmask=args.unmask, force=args.force,
                          register_method=args.register, region=args.region, cutout_size=args.cutout_size,
                          gain=args.gain)
    if args.cmd == 'mag':
        from . import mag
        started = time.strftime('%Y-%m-%dT%H:%M:%S')
        mtype = args.type or ('ph' if args.filetype == 3 else 'fit')
        res = mag.run(frames, mtype, args.match_by_site)
        for r in res:
            row = db.get_frame(r.frame)
            from pathlib import Path
            qa.write_frame(r, Path(row['filepath']) / r.frame)
        s = qa.write_summary('mag', res, params={'type': mtype}, started=started, out=QA_OUT)
        print(json.dumps({k: s[k] for k in ('stage', 'status', 'counts', 'n_frames')}))
        return qa.exit_code(s)
    if args.cmd == 'getmag':
        from . import getmag
        t = getmag.run(frames, args.type or 'mag', args.combine, args.output, keep_failed=args.keep_failed)
        if not args.output:
            t.pprint(max_lines=-1, max_width=-1)
        res = {'stage': 'getmag', 'n_points': len(t), 'n_flagged': int(sum(t['flag'])) if len(t) else 0,
               'n_qa_failed': len(t.meta['qa_failed']), 'qa_failed': t.meta['qa_failed'],
               'qa_failed_kept': args.keep_failed, 'output': args.output}
        print(json.dumps({k: v for k, v in res.items() if k != 'qa_failed'}))
        _write_json(QA_OUT, res)
        return 0 if len(t) else qa.EXIT['missing_input']
    if args.cmd == 'zcat':
        # zcat reads the other filters of the night from the DB: run serially (like lscloop)
        return _run_stage('zcat', frames, 1, _zcat, field=args.field, catalogue=args.catalogue,
                          fix=not args.unfix, rejection=args.sigma_clip, mtype=args.type, redo=args.force,
                          match_by_site=args.match_by_site)


if __name__ == '__main__':
    sys.exit(main())
