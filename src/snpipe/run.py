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
still runs independent steps). A step whose command, inputs and result are unchanged since a successful run is
not repeated (resume); ``--from STEP`` reruns STEP and everything after it.

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


def plan(analysis, choice):
    """Active steps in dependency order (stable: file order among independent steps)."""
    outs = {o['id']: o for o in analysis['outputs'] if active(o, choice)}
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


def _sig(cmd, step, state):
    """Signature of a step: its command and the signatures of the steps it depends on."""
    parts = [cmd] + [state.get(i, {}).get('sig', i) for i in step.get('inputs', [])]
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16]


def workdir_for(t, universe):
    base = Path(t['workdir'] or os.environ.get('SNPIPE_DIR') or (t['dir'] / 'work'))
    return base if universe == 'baseline' else base / f'universe-{universe}'


def run(target_dir, universe='baseline', only=None, start=None, dry_run=False, keep_going=False, analysis=None,
        echo=print):
    t = T.load(target_dir)
    tdir = Path(t['dir'])
    u, upath = load_universe(tdir, universe)
    choice = u.get('decisions', {})
    apath = Path(analysis) if analysis else recipe_dir() / 'astra.yaml'
    a = load_analysis(apath)
    steps = plan(a, choice)
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
    blocked, summary = set(), {}
    for s in steps:
        sid = s['id']
        if only and sid != only:
            summary[sid] = state.get(sid, {}).get('status', 'not run')
            continue
        cmd = expand(s['recipe']['command'].strip(), s, paths, choice, paths[sid])
        sig = _sig(cmd, s, state)
        if any(i in blocked for i in s.get('inputs', [])):
            blocked.add(sid)
            summary[sid] = 'blocked'
            echo(f'--- {sid}: blocked (an input step stopped)')
            continue
        prev = state.get(sid, {})
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
        echo(f'>>> {time.strftime("%H:%M:%S")} {sid}')
        t0 = time.time()
        with open(res / 'logs' / f'{sid}.log', 'w') as log:
            log.write(f'$ {cmd}\n')
            log.flush()
            rc = subprocess.run(cmd, shell=True, cwd=wd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        status = CONTINUE.get(rc) or STOP.get(rc, f'error_{rc}')
        state[sid] = dict(command=cmd, exit=rc, status=status, sig=sig if rc in CONTINUE else None,
                          started=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t0)),
                          seconds=round(time.time() - t0, 1), log=str(res / 'logs' / f'{sid}.log'))
        summary[sid] = status
        echo(f'<<< {sid}: {status} (exit {rc}, {state[sid]["seconds"]} s)')
        statefile.write_text(json.dumps(dict(target=t['name'], universe=universe, workdir=str(wd),
                                             code=code_version(), steps=state), indent=1))
        if rc not in CONTINUE:
            blocked.add(sid)
            echo(f'!!! {sid} stopped: see {res / "logs" / (sid + ".log")}')
            if not keep_going:
                break
    return summary, (0 if all(not str(v).startswith(('blocked', 'config', 'missing', 'external', 'error'))
                              for v in summary.values()) else 1)


def status(target_dir, universe='baseline'):
    t = T.load(target_dir)
    f = workdir_for(t, universe) / 'results' / universe / 'run.json'
    if not f.exists():
        return None
    return json.loads(f.read_text())


def init_target(path, name, ra, dec, science, templates, camera, frames='archive', aliases=(), workdir=None):
    """Write targets/<name>/target.yaml and universes/baseline.yaml (the old-pipeline defaults)."""
    d = Path(path)
    (d / 'universes').mkdir(parents=True, exist_ok=True)
    tf = d / 'target.yaml'
    if tf.exists():
        raise T.TargetError(f'{tf} exists')
    doc = {'name': name, 'aliases': list(aliases), 'ra': ra, 'dec': dec}
    if workdir:
        doc['workdir'] = str(workdir)
    doc['science'] = {'dayobs': science, 'frames': str(frames)}
    doc['templates'] = {'dayobs': templates, 'camera': camera}
    doc['resources'] = {'jobs': 8, 'diff_jobs': 2}
    tf.write_text('# Facts about the object (docs/guide/targets.md). Choices go in universes/*.yaml.\n'
                  + yaml.safe_dump(doc, sort_keys=False))
    shutil.copy(recipe_dir() / 'universes' / 'baseline.yaml', d / 'universes' / 'baseline.yaml')
    T.load(tf)
    return tf


def sbatch_script(target_dir, universe='baseline', partition='shared', hours=48, mem='32G'):
    """A SLURM job script that runs the whole recipe (resumes if resubmitted)."""
    t = T.load(target_dir)
    cpus = max(t['resources']['jobs'], 1)
    return f"""#!/bin/bash
#SBATCH -J snpipe_{t['name']}
#SBATCH -p {partition}
#SBATCH -c {cpus}
#SBATCH --mem={mem}
#SBATCH -t {hours}:00:00
#SBATCH -o {workdir_for(t, universe)}/results/{universe}/slurm_%j.log
# environment: activate the one snpipe is installed in before submitting (sbatch passes it on)
snpipe run {Path(t['dir']).resolve()} --universe {universe}
"""
