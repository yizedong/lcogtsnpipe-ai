"""``snpipe`` command line: one sub-command per stage, lscloop-like frame selection, QA + exit codes.

    snpipe add-target 2024pxl --ra 263.113958 --dec 7.062411 --alias SN2024pxl
    snpipe ingest --target 2024pxl --start 2024-07-22 --end 2024-11-10 [--local-dir DIR]
    snpipe catalogs --target 2024pxl
    snpipe cosmic|psf|zcat ... -n 2024pxl -e 20240722-20241110 [-f landolt|sloan|B V ...] [-j 8]
"""
import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from . import db, qa, sites

log = logging.getLogger('snpipe')


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
    return db.query(sql, params, conn)


def _run_stage(stage, frames, jobs, fn, **kw):
    started = time.strftime('%Y-%m-%dT%H:%M:%S')
    results = []
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            futs = [ex.submit(fn, f, **kw) for f in frames]
            results = [f.result() for f in futs]
    else:
        results = [fn(f, **kw) for f in frames]
    for r, f in zip(results, frames):
        row = db.get_frame(f)
        if row:
            from pathlib import Path
            qa.write_frame(r, Path(row['filepath']) / f)
    s = qa.write_summary(stage, results, params=kw, started=started)
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
    a.add_argument('name')
    a.add_argument('--ra', type=float, required=True)
    a.add_argument('--dec', type=float, required=True)
    a.add_argument('--alias', nargs='*', default=[])

    a = sub.add_parser('ingest')
    a.add_argument('--target', required=True, help='archive OBJECT name')
    a.add_argument('--start')
    a.add_argument('--end')
    a.add_argument('--filters', nargs='*')
    a.add_argument('--tels', nargs='*', help='1m0 0m4 2m0')
    a.add_argument('--frames-json', help='use a saved archive frame list instead of querying')
    a.add_argument('--local-dir', help='copy files from here instead of downloading')
    a.add_argument('-j', '--jobs', type=int, default=8)

    a = sub.add_parser('astra', help='write the ASTRA record of a reduction')
    a.add_argument('target')
    a.add_argument('--ra', type=float, required=True)
    a.add_argument('--dec', type=float, required=True)
    a.add_argument('--alias', nargs='*', default=[])
    a.add_argument('--epoch', required=True)
    a.add_argument('--tempdate', required=True)
    a.add_argument('--raw-dir', required=True)
    a.add_argument('--template-dir', required=True)
    a.add_argument('--out', default='astra')

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
    a.add_argument('--target', required=True)
    a.add_argument('--fields', nargs='*', default=['landolt', 'apass', 'sloan', 'gaia'])
    a.add_argument('--panstarrs', action='store_true')
    a.add_argument('--sloan-source', choices=['sdss', 'panstarrs'], default='sdss')
    a.add_argument('-F', '--force', action='store_true')

    for stage in ('cosmic', 'psf', 'psfmag', 'zcat', 'template', 'diff', 'mag', 'getmag'):
        a = sub.add_parser(stage)
        a.add_argument('-n', '--name')
        a.add_argument('-e', '--epoch')
        a.add_argument('-f', '--filter', nargs='+')
        a.add_argument('-T', '--telescope')
        a.add_argument('-d', '--id')
        a.add_argument('-b', '--bad')
        a.add_argument('--filetype', type=int, default=1)
        a.add_argument('-F', '--force', action='store_true')
        a.add_argument('-j', '--jobs', type=int, default=8)
        if stage == 'psf':
            a.add_argument('--fwhm', type=float)
            a.add_argument('--nstars', type=int, default=6)
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float, default=-100.)
            a.add_argument('--max-apercorr', type=lambda v: float(str(v).replace('apco_', '').replace('p', '.')),
                           default=0.1, help='mag (also accepts the ASTRA option ids apco_0p1, apco_0p2)')
            a.add_argument('--field', default='gaia')
            a.add_argument('--model', choices=['daophot', 'epsf'], default='daophot')
            a.add_argument('--no-auto-fix', action='store_true', help='do not run the remediation ladder')
            a.add_argument('--auto-fix', choices=['ladder', 'off'], default='ladder')
        if stage == 'psfmag':
            a.add_argument('-x', '--xord', type=int, default=3)
            a.add_argument('-y', '--yord', type=int, default=3)
            a.add_argument('--bkg', type=float, default=4.)
            a.add_argument('--size', type=float, default=7.)
            a.add_argument('-c', '--no-recenter', action='store_true')
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float)
            a.add_argument('--RA', type=float)
            a.add_argument('--DEC', type=float)
        if stage == 'diff':
            a.add_argument('--tempdate', default='19990101-20080101')
            a.add_argument('--temptel', default='')
            a.add_argument('--normalize', choices=['t', 'i'], default='t')
            a.add_argument('--unmask', action='store_true')
            a.add_argument('--register', default='exact', help='exact | bilinear | bicubic')
        if stage in ('mag', 'getmag'):
            a.add_argument('--type', choices=['fit', 'ph', 'mag'], default=None)
            a.add_argument('--match-by-site', action='store_true')
            a.add_argument('-o', '--output')
            a.add_argument('--combine', type=float, default=1e-10)
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

    if args.cmd == 'add-target':
        from . import ingest
        tid = ingest.add_target(args.name, args.ra, args.dec)
        for al in args.alias:
            if db.target_by_name(al) is None:
                db.insert('targetnames', {'name': al, 'targetid': tid, 'groupidcode': 32769})
        print(json.dumps({'targetid': tid}))
        return 0
    if args.cmd == 'ingest':
        from . import ingest
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
        tid = db.target_by_name(args.target)
        res = catalogs.run(tid, args.fields, use_panstarrs=args.panstarrs or args.sloan_source == 'panstarrs',
                           force=args.force)
        print(json.dumps(res))
        return qa.EXIT['external'] if any(v is None for v in res.values()) else 0

    if args.cmd == 'astra':
        from . import astra
        print(astra.write(args.out, args.target, args.ra, args.dec, args.epoch, args.tempdate, args.raw_dir,
                          args.template_dir, args.alias))
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
        print(json.dumps({'stage': args.cmd, 'status': 'skipped', 'n_frames': 0}))
        return qa.EXIT['missing_input']
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
                          register_method=args.register)
    if args.cmd == 'mag':
        from . import mag
        started = time.strftime('%Y-%m-%dT%H:%M:%S')
        mtype = args.type or ('ph' if args.filetype == 3 else 'fit')
        res = mag.run(frames, mtype, args.match_by_site)
        for r in res:
            row = db.get_frame(r.frame)
            from pathlib import Path
            qa.write_frame(r, Path(row['filepath']) / r.frame)
        s = qa.write_summary('mag', res, params={'type': mtype}, started=started)
        print(json.dumps({k: s[k] for k in ('stage', 'status', 'counts', 'n_frames')}))
        return qa.exit_code(s)
    if args.cmd == 'getmag':
        from . import getmag
        t = getmag.run(frames, args.type or 'mag', args.combine, args.output)
        if not args.output:
            t.pprint(max_lines=-1, max_width=-1)
        print(json.dumps({'stage': 'getmag', 'n_points': len(t), 'output': args.output}))
        return 0 if len(t) else qa.EXIT['missing_input']
    if args.cmd == 'zcat':
        # zcat reads the other filters of the night from the DB: run serially (like lscloop)
        return _run_stage('zcat', frames, 1, _zcat, field=args.field, catalogue=args.catalogue,
                          fix=not args.unfix, rejection=args.sigma_clip, mtype=args.type, redo=args.force,
                          match_by_site=args.match_by_site)


if __name__ == '__main__':
    sys.exit(main())
