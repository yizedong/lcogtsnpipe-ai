"""``snpipe run``: execute the ASTRA recipe (``pipeline/astra.yaml``) for one target.

The executor that the ASTRA format leaves to the user: it reads the analysis, the target's universe (one option
per decision) and its target file, puts the steps in dependency order, fills the recipe placeholders and runs
each command, keeping a record of what ran:

    <workdir>/results/<universe>/
        <step>.<format>        the result of each step (QA summary JSON, light-curve CSV, report)
        logs/<step>.log        everything the command printed
        run.json               per step: command, exit code, status, start, seconds; code version
        record/                frozen copies of astra.yaml, the universe and the target file that ran

Exit codes of a step decide what happens next (see the header of astra.yaml): 0 and 1 continue (1 = some frames
failed their checks and are left out downstream); 2, 3, 4 stop the steps that depend on it (``--keep-going``
still runs independent steps). ``snpipe run`` itself exits 0 when every step finished (with or without failed
frames), otherwise with the exit code of the first step that stopped.

Resume: a step is not repeated when its command, the target's facts (name, coordinates, nights, frame folders and
their frames.json), the signatures of its input steps and its result file are unchanged since it finished. When
they changed since the step was last run, the step runs with SNPIPE_FORCE=1, so the stages redo their cached
per-frame products instead of reusing them; ``--force`` does that for every step that runs. A plain resume after
an interruption forces nothing. Code changes and ``resources`` do not invalidate results: after updating the
code, rerun with ``--from STEP --force``.

A target without a ``reference`` section has no subtraction: every step downstream of the reference frames is
left out, except the review queue and the report (outputs of type ``report``), which use what exists.

A universe other than baseline gets its own working directory (``<workdir>/universe-<id>``) because the pipeline
keeps per-frame products and the database there: two sets of choices must not share them.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

import yaml

from . import target as T

CONTINUE = {0: 'ok', 1: 'qa_fail'}
STOP = {2: 'config_error', 3: 'missing_input', 4: 'external_error'}


def recipe_dir():
    return Path(str(files('snpipe').joinpath('pipeline')))


def load_analysis(path=None):
    return yaml.safe_load(Path(path or recipe_dir() / 'astra.yaml').read_text())


def load_universe(target_dir, universe):
    p = Path(target_dir) / 'universes' / f'{universe}.yaml'
    if not p.exists():
        raise T.TargetError(f'no universe file {p} (snpipe init-target writes universes/baseline.yaml)')
    u = yaml.safe_load(p.read_text())
    return u, p


def active(item, choice):
    """ASTRA ``when``: all conditions true (``decision.option`` or negated ``~decision.option``)."""
    for c in item.get('when', []) or []:
        neg = c.startswith('~')
        d, _, o = c.lstrip('~').partition('.')
        if (choice.get(d) == o) == neg:
            return False
    return True


def needs_reference(analysis, root='ingest_reference'):
    """Steps downstream of the reference frames, except collectors (type 'report')."""
    down, changed = {root}, True
    while changed:
        changed = False
        for o in analysis['outputs']:
            if o['id'] not in down and any(i in down for i in o.get('inputs', [])):
                down.add(o['id'])
                changed = True
    return {o['id'] for o in analysis['outputs'] if o['id'] in down and o.get('type') != 'report'}


def plan(analysis, choice, has_reference=True):
    """Active steps in dependency order (stable: file order among independent steps)."""
    skip = set() if has_reference else needs_reference(analysis)
    outs = {o['id']: o for o in analysis['outputs'] if active(o, choice) and o['id'] not in skip}
    inputs = {i['id'] for i in analysis.get('inputs', [])}
    inactive = {o['id'] for o in analysis['outputs']} - set(outs)
    missing = [d for d in analysis.get('decisions', {}) if d not in choice]
    if missing:
        raise T.TargetError(f'universe has no selection for decisions {missing}')
    for d, o in choice.items():
        if o not in analysis['decisions'].get(d, {}).get('options', {}):
            raise T.TargetError(f'universe selects unknown option {d}={o}')
    order, done = [], set(inputs) | inactive
    pending = list(outs)
    while pending:
        ready = [i for i in pending if all(x in done for x in outs[i].get('inputs', []))]
        if not ready:
            raise T.TargetError(f'dependency cycle or unknown input among {pending}')
        for i in ready:
            order.append(outs[i])
            done.add(i)
            pending.remove(i)
    return order


def expand(cmd, step, paths, choice, output):
    """Fill {inputs.X}, {inputs}, {decisions.X}, {output}; {{ }} are literal braces."""
    cmd = cmd.replace('{{', '\0').replace('}}', '\1')
    for i in step.get('inputs', []):
        cmd = cmd.replace('{inputs.%s}' % i, str(paths.get(i, '')))
    cmd = cmd.replace('{inputs}', ' '.join(str(paths.get(i, '')) for i in step.get('inputs', [])))
    for d in step.get('decisions', []):
        cmd = cmd.replace('{decisions.%s}' % d, str(choice[d]))
    cmd = cmd.replace('{output}', str(output))
    if '{' in cmd.replace('\0', '').replace('\1', ''):
        raise T.TargetError(f'unfilled placeholder in step {step["id"]}: {cmd}')
    return cmd.replace('\0', '{').replace('\1', '}')


def code_version():
    """Package version + git commit (and whether the checkout has uncommitted changes)."""
    from . import __version__
    src = Path(__file__).resolve().parent
    v = {'snpipe': __version__, 'python': sys.version.split()[0], 'package_dir': str(src)}
    try:
        g = lambda *a: subprocess.run(['git', '-C', str(src), *a], capture_output=True, text=True, timeout=20)
        r = g('rev-parse', 'HEAD')
        if r.returncode == 0:
            v['commit'] = r.stdout.strip()
            v['dirty'] = bool(g('status', '--porcelain', '--untracked-files=no').stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return v


def _sig(cmd, step, state, facts=''):
    """Signature of a step: its command, the target's facts and the signatures of the steps it depends on."""
    parts = [cmd, facts] + [str(state.get(i, {}).get('sig', i)) for i in step.get('inputs', [])]
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16]


def workdir_for(t, universe):
    base = Path(t['workdir'] or os.environ.get('SNPIPE_DIR') or (Path(t['dir']) / 'work'))
    return base if universe == 'baseline' else base / f'universe-{universe}'


def _print(line):
    print(line, flush=True)


def run(target_dir, universe='baseline', only=None, start=None, dry_run=False, keep_going=False, analysis=None,
        echo=_print, force=False):
    t = T.load(target_dir)
    tdir = Path(t['dir'])
    u, upath = load_universe(tdir, universe)
    choice = u.get('decisions', {})
    apath = Path(analysis) if analysis else recipe_dir() / 'astra.yaml'
    a = load_analysis(apath)
    steps = plan(a, choice, has_reference=bool(t['reference']))
    facts = T.facts(t)
    wd = workdir_for(t, universe)
    res = wd / 'results' / universe
    paths = {'target': t['file']}
    for s in steps:
        paths[s['id']] = res / f"{s['id']}.{s.get('format', 'json')}"
    env = {**os.environ, 'SNPIPE_DIR': str(wd)}
    statefile = res / 'run.json'
    state = json.loads(statefile.read_text()).get('steps', {}) if statefile.exists() else {}
    if not dry_run:
        (res / 'logs').mkdir(parents=True, exist_ok=True)
        rec = res / 'record'
        rec.mkdir(exist_ok=True)
        shutil.copy(apath, rec / 'astra.yaml')
        shutil.copy(upath, rec / f'{universe}.yaml')
        shutil.copy(t['file'], rec / 'target.yaml')
    ids = [s['id'] for s in steps]
    if only and only not in ids or start and start not in ids:
        raise T.TargetError(f'unknown step; steps are: {ids}')
    forced = set()
    if start:
        forced = set(ids[ids.index(start):])
    blocked, summary, first_stop = set(), {}, 0
    for s in steps:
        sid = s['id']
        if only and sid != only:
            summary[sid] = state.get(sid, {}).get('status', 'not run')
            continue
        cmd = expand(s['recipe']['command'].strip(), s, paths, choice, paths[sid])
        sig = _sig(cmd, s, state, facts)
        if any(i in blocked for i in s.get('inputs', [])):
            blocked.add(sid)
            summary[sid] = 'blocked'
            echo(f'--- {sid}: blocked (an input step stopped)')
            continue
        prev = state.get(sid, {})
        changed = bool(prev.get('tried_sig')) and prev['tried_sig'] != sig
        if (sid not in forced and not only and prev.get('sig') == sig and prev.get('exit') in CONTINUE
                and paths[sid].exists()):
            summary[sid] = prev['status'] + ' (done)'
            echo(f'--- {sid}: done earlier ({prev["status"]})')
            continue
        if dry_run:
            summary[sid] = 'would run'
            echo(f'>>> {sid}\n    {cmd}')
            state[sid] = {'sig': sig}
            continue
        redo = force or changed
        echo(f'>>> {time.strftime("%H:%M:%S")} {sid}' + (' (inputs or choices changed: redo cached products)' if changed
                                                          else ' (forced)' if force else ''))
        t0 = time.time()
        with open(res / 'logs' / f'{sid}.log', 'w') as log:
            log.write(f'$ {"SNPIPE_FORCE=1 " if redo else ""}{cmd}\n')
            log.flush()
            rc = subprocess.run(cmd, shell=True, cwd=wd, env={**env, 'SNPIPE_FORCE': '1' if redo else '0'},
                                stdout=log, stderr=subprocess.STDOUT).returncode
        status = CONTINUE.get(rc) or STOP.get(rc, f'error_{rc}')
        state[sid] = dict(command=cmd, exit=rc, status=status, sig=sig if rc in CONTINUE else None, tried_sig=sig,
                          forced=redo,
                          started=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t0)),
                          seconds=round(time.time() - t0, 1), log=str(res / 'logs' / f'{sid}.log'))
        summary[sid] = status
        echo(f'<<< {sid}: {status} (exit {rc}, {state[sid]["seconds"]} s)')
        statefile.write_text(json.dumps(dict(target=t['name'], universe=universe, workdir=str(wd),
                                             code=code_version(), steps=state), indent=1))
        if rc not in CONTINUE:
            first_stop = first_stop or rc
            blocked.add(sid)
            echo(f'!!! {sid} stopped: see {res / "logs" / (sid + ".log")}')
            if not keep_going:
                break
    return summary, first_stop


def status(target_dir, universe='baseline'):
    t = T.load(target_dir)
    f = workdir_for(t, universe) / 'results' / universe / 'run.json'
    if not f.exists():
        return None
    return json.loads(f.read_text())


def init_target(path, name, ra, dec, science, reference=None, camera=None, frames='archive', aliases=(),
                workdir=None):
    """Write <path>/target.yaml and universes/baseline.yaml (the old-pipeline defaults)."""
    d = Path(path)
    (d / 'universes').mkdir(parents=True, exist_ok=True)
    tf = d / 'target.yaml'
    if tf.exists():
        raise T.TargetError(f'{tf} exists')
    doc = {'schema_version': T.SCHEMA_VERSION, 'name': name, 'aliases': list(aliases), 'ra': ra, 'dec': dec}
    if workdir:
        doc['workdir'] = str(workdir)
    doc['science'] = {'dayobs': science, 'frames': str(frames)}
    if reference:
        doc['reference'] = {'dayobs': reference, 'camera': camera}
    doc['resources'] = {'jobs': 8, 'diff_jobs': 2}
    tf.write_text('# The object and its frames (docs/guide/targets.md). Method choices go in universes/*.yaml.\n'
                  + yaml.safe_dump(doc, sort_keys=False))
    shutil.copy(recipe_dir() / 'universes' / 'baseline.yaml', d / 'universes' / 'baseline.yaml')
    T.load(tf)
    return tf


def sbatch_script(target_dir, universe='baseline', hours=48):
    """A SLURM job script that runs the whole recipe (it resumes if resubmitted). Sized from the target's
    resources: cores = max(jobs, diff_jobs), memory = 8 GB per subtraction worker + 16 GB."""
    t = T.load(target_dir)
    r = t['resources']
    cpus, mem = max(r['jobs'], r['diff_jobs']), 8 * r['diff_jobs'] + 16
    parts = 'sapphire,itc_cluster' + (',shared' if mem <= 180 and cpus <= 48 else '')
    out = workdir_for(t, universe) / 'results' / universe
    return f"""#!/bin/bash
#SBATCH -J snpipe_{t['name']}
#SBATCH -p {parts}
#SBATCH -c {cpus}
#SBATCH --mem={mem}G
#SBATCH -t {hours}:00:00
#SBATCH -o {out}/slurm_%j.log
# Before sbatch: mkdir -p {out}; activate the environment snpipe is installed in (sbatch passes it on).
export OMP_NUM_THREADS=1
snpipe run {Path(t['dir']).resolve()} --universe {universe}
"""
