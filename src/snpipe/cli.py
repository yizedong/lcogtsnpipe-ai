"""``snpipe`` command line.

Whole reductions (docs/guide/running.md):
    snpipe init-target ~/reductions/sn2025xyz --name 2025xyz --ra .. --dec .. --science 20250801-20251231 \
        --reference 20260901 --camera fa --frames /data/2025xyz
    snpipe run ~/reductions/sn2025xyz [--universe baseline] [--from STEP] [--only STEP] [--dry-run]
    snpipe status ~/reductions/sn2025xyz

One stage at a time (what pipeline/astra.yaml runs; the old lscloop frame selection):
    snpipe psf --target-file ~/reductions/sn2025xyz [--frames reference] [--filetype 4] [-f B V] [-j 8]
    snpipe psf -n 2025xyz -e 20250801-20251231          (without a target file; needs SNPIPE_DIR)

Exit codes: 0 ok, 1 some frames failed their checks, 2 configuration error, 3 missing input, 4 external service.
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import db, execution, qa
from .selection import apply_target, select_frames
from .target import TargetError

STAGES = {
    'wcs': 'check the astrometry of each frame against Gaia; re-fit when it fails',
    'cosmic': 'find and clean cosmic rays',
    'psf': 'PSF model, aperture correction and star photometry of each frame',
    'psfmag': 'photometry of the transient (PSF fit and aperture)',
    'zcat': 'fit zero points and colour terms against a field catalog',
    'template': 'mark frames of the reference night as reference images (filetype 4)',
    'diff': 'difference images: science minus reference (PyZOGY)',
    'mag': 'calibrated magnitudes of the transient',
    'getmag': 'export the light curve (CSV + ECSV)',
}


def write_json(path, obj):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(obj, indent=1, default=str))


def report_result(obj, out=None):
    print(json.dumps(obj, default=str), flush=True)
    write_json(out, obj)


def _part(v):
    return 'reference' if v == 'templates' else v


def parser():
    p = argparse.ArgumentParser(prog='snpipe', description='Light curves of transients from LCO images.')
    p.add_argument('-v', '--verbose', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True, metavar='COMMAND')

    # ---- whole reductions
    a = sub.add_parser('run', help='run the whole recipe (pipeline/astra.yaml) for a target folder')
    a.add_argument('target_dir', help='folder with target.yaml and universes/')
    a.add_argument('--universe', default='baseline', help='universes/<UNIVERSE>.yaml (default baseline)')
    a.add_argument('--from', dest='start', metavar='STEP', help='rerun STEP and every step after it')
    a.add_argument('--only', metavar='STEP', help='run only STEP')
    a.add_argument('--dry-run', action='store_true', help='print the commands without running them')
    a.add_argument('--keep-going', action='store_true', help='after a stopped step, still run independent steps')
    a.add_argument('--recipe', help='another astra.yaml (default: the packaged pipeline/astra.yaml)')
    a.add_argument('--sbatch', action='store_true', help='print a SLURM job script for this run instead')
    a = sub.add_parser('status', help='what ran for a target: status, exit code and time per step')
    a.add_argument('target_dir')
    a.add_argument('--universe', default='baseline')
    a = sub.add_parser('init-target', help='create <folder>/target.yaml and universes/baseline.yaml')
    a.add_argument('target_dir')
    a.add_argument('--name', required=True, help='name in the pipeline database, e.g. 2025xyz')
    a.add_argument('--alias', nargs='*', default=[], help='other names, e.g. the archive OBJECT spellings')
    a.add_argument('--ra', type=float, required=True, help='degrees')
    a.add_argument('--dec', type=float, required=True, help='degrees')
    a.add_argument('--science', required=True, help='DAY-OBS range of the science frames, YYYYMMDD-YYYYMMDD')
    a.add_argument('--reference', '--templates', dest='reference', help='DAY-OBS of the reference night')
    a.add_argument('--camera', help='camera prefix of the reference frames (fa, fl, sq, ...)')
    a.add_argument('--frames', default='archive', help='folder with frames.json + the files, or archive')
    a.add_argument('--workdir', help='working directory (default: <folder>/work)')
    a = sub.add_parser('report', help='write the standard report of a run (report.md + figures)')
    a.add_argument('--target-file')
    a.add_argument('-o', '--output', required=True, help='results/<universe>/report.md')
    a = sub.add_parser('review-all', help='review queues (with pictures) for every step of a run')
    a.add_argument('--target-file')
    a.add_argument('--sample', type=int, default=5, help='random ok frames per step for spot checks')
    a.add_argument('-o', '--output', required=True, help='results/<universe>/review_queue.json')

    # ---- setup
    a = sub.add_parser('add-target', help='register a target (name, coordinates, aliases) in the database')
    a.add_argument('name', nargs='?')
    a.add_argument('--target-file', help='take name, coordinates and aliases from target.yaml')
    a.add_argument('--ra', type=float)
    a.add_argument('--dec', type=float)
    a.add_argument('--alias', nargs='*', default=[])
    a.add_argument('--qa-out', help='also write the result JSON here')
    a = sub.add_parser('ingest', help='copy or download frames, unpack them and register them')
    a.add_argument('--target-file', help='target.yaml: ingest its science or reference frames (--frames)')
    a.add_argument('--frames', type=_part, choices=['science', 'reference'], default='science')
    a.add_argument('--target', help='archive OBJECT name (without --target-file)')
    a.add_argument('--start', help='YYYY-MM-DD (without --target-file)')
    a.add_argument('--end', help='YYYY-MM-DD (without --target-file)')
    a.add_argument('--filters', nargs='*')
    a.add_argument('--tels', nargs='*', help='1m0 0m4 2m0')
    a.add_argument('--frames-json', help='a saved archive frame list instead of querying')
    a.add_argument('--local-dir', help='copy files from here instead of downloading')
    a.add_argument('-j', '--jobs', type=int, default=8)
    a.add_argument('--qa-out', help='also write the result JSON here')
    a = sub.add_parser('catalogs', help='field catalogs: APASS, SDSS or Pan-STARRS, Gaia')
    a.add_argument('--target-file')
    a.add_argument('--target')
    a.add_argument('--fields', nargs='*', default=['landolt', 'apass', 'sloan', 'gaia'])
    a.add_argument('--panstarrs', action='store_true', help='same as --sloan-source panstarrs')
    a.add_argument('--sloan-source', choices=['sdss', 'panstarrs'], default='sdss')
    a.add_argument('-F', '--force', action='store_true', help='query again even if a catalog is recorded')
    a.add_argument('-o', '--output', help='also write the result JSON here')

    # ---- stages
    for stage, text in STAGES.items():
        a = sub.add_parser(stage, help=text)
        g = a.add_argument_group('frame selection')
        g.add_argument('--target-file', help='target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j')
        g.add_argument('--frames', type=_part, choices=['science', 'reference'], default='science',
                       help='with --target-file: the science nights or the reference night')
        g.add_argument('-n', '--name', help='target name')
        g.add_argument('-e', '--epoch', help='DAY-OBS range YYYYMMDD-YYYYMMDD')
        g.add_argument('-f', '--filter', nargs='+', help='filters (landolt, sloan, or B V g ...)')
        g.add_argument('-T', '--telescope', help='file-name substring, e.g. a camera (fa) or site (lsc)')
        g.add_argument('-d', '--id', help='frame number')
        g.add_argument('-b', '--bad', help='only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)')
        g.add_argument('--filetype', type=int, default=1, help='1 science, 3 difference, 4 reference')
        g.add_argument('--frames-file', help='only the frame names listed in this file')
        a.add_argument('-F', '--force', action='store_true', help='redo frames that are already done')
        a.add_argument('-j', '--jobs', type=int, default=None, help='frames in parallel (default 8, diff 2)')
        a.add_argument('--qa-out', help='also write the stage summary JSON here')
        if stage == 'psf':
            a.add_argument('--fwhm', type=float)
            a.add_argument('--nstars', type=lambda v: int(str(v).lstrip('n')), default=6,
                           help='number of PSF stars (also accepts the recipe option ids n6, n12, n20)')
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float, default=-100.)
            a.add_argument('--max-apercorr', type=lambda v: float(str(v).replace('apco_', '').replace('p', '.')),
                           default=0.1, help='mag (also accepts the recipe option ids apco_0p1, apco_0p2)')
            a.add_argument('--field', default='gaia', help='catalog for the star list')
            a.add_argument('--model', choices=['daophot', 'epsf'], default='daophot')
            a.add_argument('--auto-fix', choices=['ladder', 'off'], default='ladder',
                           help="retry failed PSFs with the manual's fixes")
        if stage == 'psfmag':
            order = lambda v: int(str(v).replace('order', ''))
            a.add_argument('-x', '--xord', type=order, default=3, help='background order in x (or order1, order3)')
            a.add_argument('-y', '--yord', type=order, default=3, help='background order in y')
            a.add_argument('--bkg', type=float, default=4.)
            a.add_argument('--size', type=float, default=7.)
            a.add_argument('-c', '--no-recenter', action='store_true')
            a.add_argument('--datamax', type=float)
            a.add_argument('--datamin', type=float)
            a.add_argument('--RA', type=float)
            a.add_argument('--DEC', type=float)
        if stage == 'diff':
            a.add_argument('--tempdate', default=None, help='DAY-OBS (range) of the reference frames')
            a.add_argument('--temptel', default='', help='camera prefix of the reference frames (fa, fl, sq ...)')
            a.add_argument('--normalize', choices=['t', 'i'], default='t', help='flux scale: reference (t) or science (i)')
            a.add_argument('--unmask', action='store_true')
            a.add_argument('--register', default='adaptive', help='adaptive | exact | bilinear | bicubic')
            a.add_argument('--region', choices=['full', 'cutout'], default='full')
            a.add_argument('--gain', choices=['zeropoint', 'fit'], default='zeropoint',
                           help='flux ratio science/reference: from the zero points (default) or the PyZOGY fit '
                                '(old default, biased low: bug O01)')
            a.add_argument('--cutout-size', type=int, default=2048)
            a.add_argument('--reference-class', choices=['same', 'any'], default='same',
                           help="with --target-file: subtract only with a reference of the frame's own telescope "
                                'class (same, the manual) or fall back to another class (any)')
        if stage in ('mag', 'getmag'):
            a.add_argument('--type', choices=['fit', 'ph', 'mag'], default=None,
                           help='fit = PSF, ph = aperture, mag = calibrated (getmag)')
            a.add_argument('--match-by-site', action='store_true')
            a.add_argument('-o', '--output', help='getmag: light-curve CSV (an ECSV is written next to it)')
            a.add_argument('--combine', type=float, default=1e-10, help='getmag: average points closer than this (days)')
            if stage == 'getmag':
                a.add_argument('--keep-failed', action='store_true', help='keep points whose checks failed')
        if stage == 'zcat':
            a.add_argument('--field', default='', help='catalog system: apass, sloan, landolt')
            a.add_argument('--catalogue', default='')
            a.add_argument('--unfix', action='store_true', help='fit the colour term instead of fixing it')
            a.add_argument('--type', choices=['fit', 'ph'], default='fit', help='star magnitudes: PSF or aperture')
            a.add_argument('--sigma-clip', type=float, default=2.)
            a.add_argument('--match-by-site', action='store_true')

    # ---- review
    a = sub.add_parser('review', help='review queue and pictures for one stage (last call of that stage)')
    a.add_argument('stage')
    a.add_argument('--frame', help='make the picture of one frame')
    a.add_argument('--sample', type=int, default=5)
    a.add_argument('--ensemble', nargs='*', help='metrics to compare against peer frames')
    a = sub.add_parser('verdict', help='record a review verdict (agent or person) and apply its effect')
    a.add_argument('frame')
    a.add_argument('stage')
    a.add_argument('verdict', choices=['accept', 'redo', 'bad', 'delete', 'ulim'])
    a.add_argument('--reason', required=True)
    a.add_argument('--param', nargs='*', default=[], help='key=value remediation knobs for redo')
    a.add_argument('--who', default='agent')
    return p


# ---------------------------------------------------------------- whole reductions

def cmd_run(args):
    from . import run
    if args.sbatch:
        print(run.sbatch_script(args.target_dir, args.universe))
        return 0
    summary, rc = run.run(args.target_dir, args.universe, only=args.only, start=args.start, dry_run=args.dry_run,
                          keep_going=args.keep_going, analysis=args.recipe)
    print(json.dumps(summary, indent=1))
    return rc


def cmd_status(args):
    from . import run
    s = run.status(args.target_dir, args.universe)
    if s is None:
        print(json.dumps({'status': 'not run'}))
        return 0
    print(f"{s['target']} / {s['universe']}  workdir {s['workdir']}  commit {s['code'].get('commit', '?')[:10]}")
    for sid, st in s['steps'].items():
        print(f"  {sid:26s} {st.get('status', ''):15s} exit {st.get('exit', ''):>2}  {st.get('seconds', '')} s")
    return 0


def cmd_init_target(args):
    from . import run
    if bool(args.reference) != bool(args.camera):
        raise TargetError('give both --reference and --camera, or neither (no subtraction)')
    f = run.init_target(args.target_dir, args.name, args.ra, args.dec, args.science, args.reference, args.camera,
                        args.frames, args.alias, args.workdir)
    print(json.dumps({'target_file': str(f)}))
    return 0


def cmd_report(args):
    from . import report
    print(json.dumps({'report': str(report.write(args.output, args.target_file))}))
    return 0


def cmd_review_all(args):
    from . import review
    q = review.review_all(args.output, args.sample)
    print(json.dumps({k: v.get('n_items', v.get('error')) for k, v in q.items()}))
    return 0


# ---------------------------------------------------------------- setup

def _target(args):
    if not getattr(args, 'target_file', None):
        return None
    from . import target
    t = target.load(args.target_file)
    target.activate(t)
    return t


def cmd_add_target(args):
    from . import ingest
    t = _target(args)
    if t:
        args.name, args.ra, args.dec, args.alias = t['name'], float(t['ra']), float(t['dec']), t['aliases']
    if args.name is None or args.ra is None or args.dec is None:
        raise TargetError('give NAME --ra --dec, or --target-file')
    tid = ingest.add_target(args.name, args.ra, args.dec)
    for al in args.alias:
        if db.target_by_name(al) is None:
            db.insert('targetnames', {'name': al, 'targetid': tid, 'groupidcode': 32769})
    report_result({'targetid': tid, 'name': args.name, 'ra': args.ra, 'dec': args.dec, 'aliases': args.alias},
                  args.qa_out)
    return 0


def cmd_ingest(args):
    from . import ingest, target
    t = _target(args)
    keep = lambda f: ((not args.filters or f['primary_optical_element'] in args.filters)
                      and (not args.tels or f['TELID'][:3] in args.tels))
    if t:
        tid = db.target_by_name(t['name'])
        if tid is None:
            raise TargetError(f"target {t['name']} is not in the database: run add-target first")
        frames, local = target.frames_for(t, args.frames)
        frames = [f for f in frames if keep(f)]
        paths, new = ingest.run(frames, local, args.jobs, targetid=tid)
        res = {'part': args.frames, 'dayobs': t[args.frames]['dayobs']}
    else:
        if not args.target:
            raise TargetError('give --target or --target-file')
        frames = (json.load(open(args.frames_json)) if args.frames_json else
                  ingest.query_archive(OBJECT=args.target, start=args.start, end=args.end, RLEVEL=91,
                                       configuration_type='EXPOSE'))
        frames = [f for f in frames if keep(f)]
        paths, new = ingest.run(frames, args.local_dir, args.jobs)
        res = {}
    placed = {p.name for p in paths}
    missing = sorted(f['filename'] for f in frames if f['filename'].replace('.fz', '') not in placed)
    report_result({**res, 'frames': len(frames), 'placed': len(paths), 'new_rows': new, 'missing': missing}, args.qa_out)
    return qa.EXIT['ok'] if frames and not missing else qa.EXIT['missing_input']


def cmd_catalogs(args):
    from . import catalogs
    t = _target(args)
    tid = db.target_by_name(t['name'] if t else (args.target or ''))
    if tid is None:
        raise TargetError('unknown target: run add-target first')
    res = catalogs.run(tid, args.fields, use_panstarrs=args.panstarrs or args.sloan_source == 'panstarrs',
                       force=args.force)
    report_result(res, args.output)
    return qa.EXIT['external'] if any(v is None for v in res.values()) else 0


# ---------------------------------------------------------------- stages

def cmd_stage(args):
    apply_target(args)
    if args.jobs is None:
        args.jobs = 2 if args.cmd == 'diff' else 8
    if args.cmd == 'diff' and args.tempdate is None and getattr(args, 'references', None) is None:
        raise TargetError('diff needs --tempdate/--temptel (or a --target-file with a reference section)')
    frames = [r['filename'] for r in select_frames(args)]
    if not frames:
        report_result({'stage': args.cmd, 'status': 'skipped', 'n_frames': 0,
                       'message': 'no frames selected (check -n/-e/--filetype, or run the earlier stages)'}, args.qa_out)
        return qa.EXIT['missing_input']
    run = lambda fn, jobs, **kw: execution.run_stage(args.cmd, frames, jobs, fn, qa_out=args.qa_out, **kw)
    if args.cmd == 'wcs':
        return run(execution.wcs, args.jobs, force=args.force)
    if args.cmd == 'cosmic':
        return run(execution.cosmic, args.jobs, force=args.force)
    if args.cmd == 'psf':
        return run(execution.psf, args.jobs, redo=args.force, fwhm=args.fwhm, nstars=args.nstars,
                   datamax=args.datamax, datamin=args.datamin, max_apercorr=args.max_apercorr, field=args.field,
                   model=args.model, auto_fix=args.auto_fix == 'ladder')
    if args.cmd == 'psfmag':
        return run(execution.psfmag, args.jobs, redo=args.force, xord=args.xord, yord=args.yord, bkg=args.bkg,
                   size=args.size, recenter=not args.no_recenter, datamax=args.datamax, datamin=args.datamin,
                   ra=args.RA, dec=args.DEC)
    if args.cmd == 'template':
        return run(execution.template, 1, force=args.force)
    if args.cmd == 'diff':
        return run(execution.diff, args.jobs, tempdate=args.tempdate, temptel=args.temptel, normalize=args.normalize,
                   unmask=args.unmask, force=args.force, register_method=args.register, region=args.region,
                   cutout_size=args.cutout_size, gain=args.gain, references=getattr(args, 'references', None),
                   reference_class=args.reference_class)
    if args.cmd == 'zcat':
        # zcat reads the other filters of the night from the database: serial, like lscloop
        return run(execution.zcat, 1, field=args.field, catalogue=args.catalogue, fix=not args.unfix,
                   rejection=args.sigma_clip, mtype=args.type, redo=args.force, match_by_site=args.match_by_site)
    if args.cmd == 'mag':
        from . import mag
        started = time.strftime('%Y-%m-%dT%H:%M:%S')
        mtype = args.type or ('ph' if args.filetype == 3 else 'fit')
        results = mag.run(frames, mtype, args.match_by_site)
        for r in results:
            qa.write_frame(r, Path(db.get_frame(r.frame)['filepath']) / r.frame)
        return execution.finish('mag', results, {'type': mtype}, started, args.qa_out)
    if args.cmd == 'getmag':
        from . import getmag
        t = getmag.run(frames, args.type or 'mag', args.combine, args.output, keep_failed=args.keep_failed)
        if not args.output:
            t.pprint(max_lines=-1, max_width=-1)
        res = {'stage': 'getmag', 'n_points': len(t), 'n_flagged': int(sum(t['flag'])) if len(t) else 0,
               'n_qa_failed': len(t.meta['qa_failed']), 'qa_failed': t.meta['qa_failed'],
               'qa_failed_kept': args.keep_failed, 'output': args.output}
        print(json.dumps({k: v for k, v in res.items() if k != 'qa_failed'}), flush=True)
        write_json(args.qa_out, res)
        return 0 if len(t) else qa.EXIT['missing_input']


# ---------------------------------------------------------------- review

def cmd_review(args):
    from . import review
    if args.frame:
        print(review.packet(args.stage, args.frame))
        return 0
    if args.ensemble:
        print(json.dumps(review.ensemble(args.stage, args.ensemble), indent=1))
    print(review.queue(args.stage, args.sample))
    return 0


def cmd_verdict(args):
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


HANDLERS = {'run': cmd_run, 'status': cmd_status, 'init-target': cmd_init_target, 'report': cmd_report,
            'review-all': cmd_review_all, 'add-target': cmd_add_target, 'ingest': cmd_ingest,
            'catalogs': cmd_catalogs, 'review': cmd_review, 'verdict': cmd_verdict,
            **{s: cmd_stage for s in STAGES}}


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    try:
        return HANDLERS[args.cmd](args)
    except TargetError as e:
        print(json.dumps({'error': str(e)}), flush=True)
        return qa.EXIT['config']


if __name__ == '__main__':
    sys.exit(main())
