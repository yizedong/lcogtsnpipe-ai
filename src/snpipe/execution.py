"""Running one stage over many frames: in parallel, one frame's failure never stops the others, every frame's
check result is written as soon as it is done, and the stage summary is written at the end."""
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import config, db, qa


def safe(fn, frame, stage, **kw):
    """An exception in one frame becomes a 'fail' result for that frame."""
    try:
        return fn(frame, **kw)
    except Exception as e:
        q = qa.FrameQA(frame, stage)
        q.fail(f'{type(e).__name__}: {e}')
        q.metrics['traceback'] = traceback.format_exc(limit=3)
        return q


def write_frame_qa(r):
    """``<frame>.<stage>.qa.json`` next to the image; a 'skipped' result never overwrites an earlier one."""
    row = db.get_frame(r.frame)
    if not row:
        return
    path = Path(row['filepath']) / r.frame
    if r.status == 'skipped' and Path(str(path).replace('.fits', f'.{r.stage}.qa.json')).exists():
        return
    qa.write_frame(r, path)


def run_stage(stage, frames, jobs, fn, qa_out=None, **kw):
    """Run ``fn(frame, **kw)`` on every frame; print and write the summary; return the exit code."""
    started = time.strftime('%Y-%m-%dT%H:%M:%S')
    results = []
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            futs = [ex.submit(safe, fn, f, stage, **kw) for f in frames]
            for fut in as_completed(futs):
                r = fut.result()
                write_frame_qa(r)
                results.append(r)
    else:
        for f in frames:
            r = safe(fn, f, stage, **kw)
            write_frame_qa(r)
            results.append(r)
    return finish(stage, results, kw, started, qa_out)


def finish(stage, results, params, started, qa_out=None):
    s = qa.write_summary(stage, results, params=params, started=started, out=qa_out)
    print(json.dumps({k: s[k] for k in ('stage', 'status', 'counts', 'n_frames', 'wall_seconds')}), flush=True)
    return qa.exit_code(s)


# ---- per-frame workers (module-level so that worker processes can import them)

def cosmic(frame, force=False):
    from . import cosmic as m
    row = db.get_frame(frame)
    return m.run_one(Path(row['filepath']) / frame, force=force)


def redo_params(stage, frame):
    """Remediation knobs left by a reviewer's 'redo' verdict (review/redo_params.json)."""
    f = config.workdir() / 'review' / 'redo_params.json'
    return json.loads(f.read_text()).get(stage, {}).get(frame, {}) if f.exists() else {}


def psf(frame, **kw):
    from . import psf as m
    extra = redo_params('psf', frame)
    if extra:
        kw = {**kw, **extra, 'redo': True}
    return m.run_one(frame, **kw)


def psfmag(frame, **kw):
    from . import psfmag as m
    return m.run_one(frame, **kw)


def wcs(frame, **kw):
    from . import wcs as m
    return m.run_one(frame, **kw)


def template(frame, **kw):
    from . import template as m
    return m.run_one(frame, **kw)


def diff(frame, **kw):
    from . import diff as m
    return m.run_one(frame, **kw)


def zcat(frame, **kw):
    from . import zcat as m
    return m.run_one(frame, **kw)
