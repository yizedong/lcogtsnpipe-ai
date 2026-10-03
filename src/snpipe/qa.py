"""Machine-checkable stage products for agents.

Every stage writes
* one ``<frame>.<stage>.qa.json`` per frame next to the image: status ok|warn|fail|skipped, metrics,
  the thresholds they were judged against, and messages;
* one ``qa/<stage>-<timestamp>.json`` summary in the work directory (+ ``qa/<stage>-latest.json``);
and the CLI exits with a code an agent can gate on (see EXIT).
"""
import hashlib
import json
import math
import platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__, config

EXIT = {'ok': 0, 'qa_fail': 1, 'config': 2, 'missing_input': 3, 'external': 4}
STATUS_ORDER = ('ok', 'skipped', 'warn', 'fail')


@dataclass
class FrameQA:
    frame: str
    stage: str
    status: str = 'ok'
    metrics: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    seconds: float = 0.0

    def fail(self, msg):
        self.status = 'fail'
        self.messages.append(msg)
        return self

    def warn(self, msg):
        if self.status == 'ok':
            self.status = 'warn'
        self.messages.append(msg)
        return self

    def check(self, name, value, lo=None, hi=None, severity='fail'):
        """Record a metric and judge it against [lo, hi]."""
        self.metrics[name] = value
        self.thresholds[name] = [lo, hi]
        try:
            finite = value is not None and math.isfinite(value)
        except TypeError:
            finite = value is not None
        # NaN compares False with every bound: treat a non-finite metric as out of range
        bad = not finite or (lo is not None and value < lo) or (hi is not None and value > hi)
        if bad:
            (self.fail if severity == 'fail' else self.warn)(f'{name}={value} outside [{lo}, {hi}]')
        return not bad


def _jsonable(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


def sha256(path, nbytes=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while chunk := fh.read(nbytes):
            h.update(chunk)
    return h.hexdigest()


def write_frame(qa: FrameQA, image_path):
    out = Path(str(image_path).replace('.fits', f'.{qa.stage}.qa.json'))
    out.write_text(json.dumps(asdict(qa), indent=1, default=_jsonable))
    return out


# a 'skipped' frame is either already done (fine) or missing a prerequisite (an earlier stage did not run or
# failed). Messages of the first kind contain one of these words; every other skip counts as missing input.
DONE_WORDS = ('already', 'exists', 'no reference for this telescope class', 'no reference in this filter')


def skipped_missing(frames):
    return [f.frame for f in frames if f.status == 'skipped' and not any(w in ' '.join(f.messages) for w in DONE_WORDS)]


def write_summary(stage, frames, params=None, started=None, out=None):
    counts = {s: sum(f.status == s for f in frames) for s in STATUS_ORDER}
    missing = skipped_missing(frames)
    summary = {
        'stage': stage,
        'status': 'fail' if counts['fail'] else ('warn' if counts['warn'] else 'ok'),
        'counts': counts,
        'skipped_missing_input': missing,
        'n_frames': len(frames),
        'params': params or {},
        'software': {'snpipe': __version__, 'python': platform.python_version()},
        'started': started,
        'finished': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'wall_seconds': round(time.time() - time.mktime(time.strptime(started, '%Y-%m-%dT%H:%M:%S')), 1)
        if started else None,
        'frames': [asdict(f) for f in frames],
    }
    d = config.workdir() / 'qa'
    d.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%S')
    text = json.dumps(summary, indent=1, default=_jsonable)
    (d / f'{stage}-{stamp}.json').write_text(text)
    (d / f'{stage}-latest.json').write_text(text)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text)
    return summary


def exit_code(summary):
    """1 if any frame failed its gates; 3 if no frame could be processed at all because its inputs were missing
    (every skipped frame lacked an earlier stage's product); else 0 (frames already done count as done)."""
    c = summary['counts']
    if c['fail']:
        return EXIT['qa_fail']
    missing = summary.get('skipped_missing_input') or []
    if not (c['ok'] or c['warn']) and missing and len(missing) == c['skipped']:
        return EXIT['missing_input']
    return EXIT['ok']
