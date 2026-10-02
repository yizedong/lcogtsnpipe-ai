"""The standard output of a reduction: review queues and the report (steps ``review_queue`` and ``report``).

Both read the results folder of a run (``<workdir>/results/<universe>/``, the folder of ``-o``): the per-step
QA summaries, ``run.json`` and the light curves written by ``getmag``.

report.md contains, in this order: the target and the choices (universe), the code version, one line per step
(status, frames ok/warn/fail/skipped, time), the light curves (plot + points per band), every frame left out of
a light curve and why, the review queue, and how to reproduce the run.
"""
import json
from pathlib import Path

import numpy as np

from . import review

LC = (('lc_subtracted', 'with template subtraction (main product)'), ('lc_unsubtracted', 'without subtraction (includes host light)'))


def _load(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def review_all(output, sample=5):
    """One review queue per step that has per-frame results (warn/fail + a random ok sample, with packets)."""
    res = Path(output).parent
    queues = {}
    for f in sorted(res.glob('*.json')):
        s = _load(f)
        if not isinstance(s, dict) or not s.get('frames') or s.get('stage') not in review.QUESTIONS:
            continue
        try:
            q = review.queue(s['stage'], sample=sample, summary=f, name=f.stem)
            items = json.loads(q.read_text())['items']
            queues[f.stem] = dict(stage=s['stage'], queue=str(q), n_items=len(items),
                                  n_warn_fail=sum(i['reason'] == 'warn/fail' for i in items))
        except Exception as e:
            queues[f.stem] = dict(stage=s['stage'], error=f'{type(e).__name__}: {e}')
    Path(output).write_text(json.dumps(queues, indent=1))
    return queues


def _plot(res, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from astropy.table import Table
    colors = {'U': '#6a3d9a', 'B': '#1f78b4', 'V': '#33a02c', 'g': '#b2df8a', 'r': '#e31a1c', 'i': '#ff7f00',
              'z': '#8c510a', 'w': '#999999'}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    any_points = False
    for ax, (name, title) in zip(axes, LC):
        f = res / f'{name}.ecsv'
        if not f.exists():
            ax.set_title(f'{name}: not produced')
            continue
        t = Table.read(f)
        for band in sorted(set(t['filter']), key=lambda b: 'UBVgriwz'.find(b)):
            s = t[t['filter'] == band]
            fl = np.asarray(s['flag'], bool) if 'flag' in s.colnames else np.zeros(len(s), bool)
            c = colors.get(band, 'k')
            ax.errorbar(s['jd'][~fl] - 2400000.5, s['mag'][~fl], s['dmag'][~fl], fmt='o', ms=3, color=c, label=band)
            if fl.any():
                ax.plot(s['jd'][fl] - 2400000.5, s['mag'][fl], 'o', mfc='none', mec=c, ms=7)
            any_points = True
        ax.set_title(f'{name}\n{title}', fontsize=10)
        ax.set_xlabel('MJD')
        ax.legend(fontsize=8, ncol=2)
    axes[0].set_ylabel('mag')
    axes[0].invert_yaxis()
    fig.text(0.5, 0.005, 'open circles: points flagged by the light-curve outlier check (kept for review)',
             ha='center', fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=90)
    plt.close(fig)
    return any_points


def write(output, target_file=None):
    from astropy.table import Table
    from . import target as T
    res = Path(output).parent
    run = _load(res / 'run.json') or {}
    t = T.load(target_file) if target_file else None
    rec = res / 'record'
    uni = next(iter(sorted(rec.glob('*.yaml'))), None) if rec.exists() else None
    import yaml
    choice = {}
    for f in (sorted(rec.glob('*.yaml')) if rec.exists() else []):
        d = yaml.safe_load(f.read_text())
        if isinstance(d, dict) and 'decisions' in d and 'id' in d and 'outputs' not in d:
            choice, uni = d['decisions'], f
    L = []
    name = t['name'] if t else run.get('target', '?')
    L += [f'# Reduction report: {name}', '']
    if t:
        L += [f"RA {float(t['ra']):.6f}, Dec {float(t['dec']):+.6f} · science DAY-OBS {t['science']['dayobs']} · "
              f"reference DAY-OBS {t['templates']['dayobs']} (camera {t['templates']['camera']}) · "
              f"workdir `{run.get('workdir', '')}`", '']
    code = run.get('code', {})
    L += [f"Code: snpipe {code.get('snpipe', '?')}, commit `{code.get('commit', 'unknown')}`"
          + (' **with uncommitted changes**' if code.get('dirty') else '') + f", Python {code.get('python', '?')}.",
          f"Universe `{run.get('universe', '?')}`: " + ', '.join(f'{k}={v}' for k, v in choice.items()), '']

    L += ['## Steps', '', '| step | status | ok | warn | fail | skipped | seconds |', '|---|---|---|---|---|---|---|']
    for sid, st in run.get('steps', {}).items():
        s = _load(res / f'{sid}.json') or {}
        c = s.get('counts', {}) if isinstance(s, dict) else {}
        L.append(f"| {sid} | {st.get('status', '')} | {c.get('ok', '')} | {c.get('warn', '')} | {c.get('fail', '')} | "
                 f"{c.get('skipped', '')} | {st.get('seconds', '')} |")
    L += ['', 'Status: ok; qa_fail = some frames failed their checks and are left out downstream; config_error, '
          'missing_input, external_error = the step stopped (see results/<universe>/logs/<step>.log).', '']

    L += ['## Light curves', '']
    png = res / 'report_lightcurve.png'
    try:
        if _plot(res, png):
            L += [f'![light curves]({png.name})', '']
    except Exception as e:
        L += [f'(plot failed: {type(e).__name__}: {e})', '']
    for lc, title in LC:
        f = res / f'{lc}.ecsv'
        if not f.exists():
            L += [f'**{lc}**: not produced.', '']
            continue
        tb = Table.read(f)
        L += [f'**{lc}** ({title}): `{lc}.csv` / `{lc}.ecsv`, {len(tb)} points.', '',
              '| band | points | flagged | first MJD | last MJD | brightest mag |', '|---|---|---|---|---|---|']
        for band in sorted(set(tb['filter']), key=lambda b: 'UBVgriwz'.find(b)):
            s = tb[tb['filter'] == band]
            L.append(f"| {band} | {len(s)} | {int(np.sum(s['flag'])) if 'flag' in s.colnames else 0} | "
                     f"{min(s['jd']) - 2400000.5:.2f} | {max(s['jd']) - 2400000.5:.2f} | {min(s['mag']):.3f} |")
        failed = tb.meta.get('qa_failed', {})
        L += ['', f'Left out because a check failed: {len(failed)} frames.', '']
        if failed:
            L += ['| frame | failed checks |', '|---|---|']
            L += [f'| {k} | {", ".join(v)} |' for k, v in sorted(failed.items())]
            L.append('')
        if 'flag' in tb.colnames and np.any(tb['flag']):
            L += ['Flagged (kept, outlier against neighbours in time; look at these):', '']
            L += [f"- {r['filename']} {r['filter']} {r['mag']:.3f}±{r['dmag']:.3f}" for r in tb[np.asarray(tb['flag'], bool)]]
            L.append('')

    q = _load(res / 'review_queue.json') or {}
    if q:
        L += ['## Review queue', '', 'Every warn/fail frame plus a random sample of ok frames per step, with a PNG '
              'packet each. Give verdicts with `snpipe verdict FRAME STAGE accept|redo|bad|delete|ulim --reason ...` '
              '(docs/guide/review.md).', '', '| step | items | warn/fail | queue |', '|---|---|---|---|']
        for sid, v in q.items():
            L.append(f"| {sid} | {v.get('n_items', '')} | {v.get('n_warn_fail', '')} | `{v.get('queue', v.get('error', ''))}` |")
        L.append('')
    L += ['## Reproduce', '', f"`snpipe run {t['dir'] if t else '<target folder>'} --universe {run.get('universe', 'baseline')}` "
          f"with the code commit above; the exact recipe, universe and target file are in `{rec}`.", '']
    Path(output).write_text('\n'.join(L))
    return output
