"""Agent review: what a human used to inspect in the interactive ``check*`` stages, as files.

* ``packet(stage, frame)``: one PNG with a fixed layout + a JSON sidecar (numbers, the question asked,
  allowed verdicts) per frame and check. Written to ``review/<stage>/<frame>.png|.json``.
* ``queue(stage)``: every warn/fail frame of the latest stage summary plus a random sample of ok frames
  (spot check), with packet paths -> ``review/<stage>/queue.json``.
* ``ensemble(stage)``: robust z-scores of per-frame metrics against frames of the same filter and
  telescope class (what a human learns as "what this field looks like in this filter") -> warn flags.
* ``verdict(frame, stage, v, reason, params)``: the old y/n/b/d/u effects on the DB, logged to
  ``review/verdicts.jsonl``; ``redo`` stores remediation knobs that the next run of the stage applies.
"""
import json
import random
import time
from pathlib import Path

import numpy as np

from . import config, db

QUESTIONS = {
    'wcs': ('Do the catalog stars (circles) sit on the stars of the image, everywhere in the field?',
            {'accept': 'keep', 'redo': 'wcs=9999, psf=X (rerun wcs)', 'bad': 'quality=1', 'delete': 'remove frame'}),
    'cosmic': ('Does the mask flag only cosmic rays (not the target or star cores)?',
               {'accept': 'keep', 'redo': 'remove mask/clean (rerun cosmic)', 'bad': 'quality=1'}),
    'psf': ('Are the PSF stars isolated, unsaturated single stars, and do model and residuals look clean?',
            {'accept': 'keep', 'redo': 'psf=X, psfmag=9999 (rerun psf with params)', 'bad': 'quality=1'}),
    'zcat': ('Is the zero-point fit (green kept, red rejected) a sensible straight line?',
             {'accept': 'keep', 'redo': 'zcat=X (rerun with params)', 'bad': 'quality=1'}),
    'psfmag': ('Is the target well fitted (residual consistent with noise, no neighbour/edge problems)?',
               {'accept': 'keep', 'redo': 'mags=9999 (rerun)', 'bad': 'quality=1', 'ulim': 'magtype=-1'}),
    'diff': ('Is the difference clean around field stars, with the target as the only real residual?',
             {'accept': 'keep', 'delete': 'remove the difference image'}),
    'getmag': ('Is this light-curve point consistent with its neighbours in time and band?',
               {'accept': 'keep', 'delete': 'mags=9999 (rerun from psf)', 'ulim': 'magtype=-1', 'bad': 'quality=1'}),
}
REDO_PARAMS = {  # remediation knobs the manual lists per stage
    'psf': {'fwhm', 'datamax', 'datamin', 'nstars', 'field', 'use_sextractor', 'model'},
    'wcs': {'catalog', 'xshift', 'yshift', 'mode'},
    'psfmag': {'datamax', 'datamin', 'size', 'bkg', 'xord', 'yord'},
    'zcat': {'field', 'catalogue', 'unfix', 'sigma_clip'},
    'diff': {'unmask', 'normalize', 'tempdate', 'temptel'},
}


def _rdir(stage):
    d = config.workdir() / 'review' / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _zscale(a):
    from astropy.visualization import ZScaleInterval
    return ZScaleInterval().get_limits(a[np.isfinite(a)])


def packet(stage, frame, conn=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from astropy.io import fits
    row = db.get_frame(frame, conn)
    img = Path(row['filepath']) / frame
    qafile = Path(str(img).replace('.fits', f'.{stage}.qa.json'))
    if stage == 'diff' and not qafile.exists():   # diff QA is filed under the science frame
        qafile = Path(row['filepath']) / (frame.split('.optimal')[0] + '.diff.qa.json')
    qa = json.loads(qafile.read_text()) if qafile.exists() else {}
    out = _rdir(stage) / frame.replace('.fits', '.png')
    if stage == 'psf':
        from .psf import PSFModel
        pm = PSFModel.read(str(img).replace('.fits', '.psf.fits'))
        data = fits.getdata(img).astype(float)
        fig, ax = plt.subplots(2, 4, figsize=(16, 8))
        lo, hi = _zscale(data[::8, ::8])
        ax[0, 0].imshow(data, origin='lower', cmap='gray', vmin=lo, vmax=hi)
        with fits.open(str(img).replace('.fits', '.psf.fits')) as f:
            h = f[0].header
            n = h.get('NPSFSTAR', 0)
            xs = [h[f'X{i}'] - 1 for i in range(1, n + 1)]
            ys = [h[f'Y{i}'] - 1 for i in range(1, n + 1)]
        ax[0, 0].scatter(xs, ys, s=80, facecolors='none', edgecolors='c')
        ax[0, 0].set_title('PSF stars (cyan)')
        ax[0, 1].imshow(pm.image(), origin='lower')
        ax[0, 1].set_title('PSF model')
        r = np.hypot(*np.meshgrid(np.arange(-pm.psfrad, pm.psfrad + 1), np.arange(-pm.psfrad, pm.psfrad + 1)))
        ax[0, 2].plot(r.ravel(), (pm.image() / pm.image().max()).ravel(), '.', ms=2)
        ax[0, 2].set_title('radial profile (model)')
        ax[0, 3].axis('off')
        m = qa.get('metrics', {})
        ax[0, 3].text(0, 1, '\n'.join(f'{k}: {m.get(k)}' for k in ('apco', 'apco_err', 'n_psf_stars',
                      'fwhm_input_pix', 'fwhm_psf_x_pix', 'fwhm_psf_y_pix', 'accepted_attempt')), va='top', family='monospace')
        R = int(pm.psfrad)
        base = pm.photutils()
        for k, (x, y) in enumerate(zip(xs[:4], ys[:4])):
            xi, yi = int(round(x)), int(round(y))
            stamp = data[yi - R:yi + R + 1, xi - R:xi + R + 1]
            if stamp.shape != (2 * R + 1, 2 * R + 1):
                continue
            yy, xx = np.mgrid[yi - R:yi + R + 1, xi - R:xi + R + 1]
            prof = base.evaluate(xx, yy, 1., x, y)            # model at the sub-pixel star position
            A = np.c_[prof.ravel(), np.ones(prof.size)]
            (flux, sky), *_ = np.linalg.lstsq(A, stamp.ravel(), rcond=None)
            res = stamp - flux * prof - sky
            peak = flux * prof.max()
            ax[1, k].imshow(res, origin='lower', cmap='RdBu_r', vmin=-0.05 * peak, vmax=0.05 * peak)
            ax[1, k].set_title(f'PSF star {k + 1}: data - model (+-5% of peak)')
    elif stage == 'psfmag':
        fig, ax = plt.subplots(1, 3, figsize=(12, 4))
        for a, suf, t in zip(ax, ('.og.fits', '.sf.fits', '.rs.fits'), ('original', 'original - fit', 'residual')):
            d = fits.getdata(str(img).replace('.fits', suf))
            lo, hi = _zscale(fits.getdata(str(img).replace('.fits', '.og.fits')))
            a.imshow(d, origin='lower', cmap='gray', vmin=lo, vmax=hi)
            a.set_title(t)
        m = qa.get('metrics', {})
        fig.suptitle(f"{frame}  {row['filter']}  psfmag={m.get('psfmag')}+-{m.get('psfdmag')}  apmag={m.get('apmag')}")
    elif stage == 'diff':
        fig, ax = plt.subplots(1, 3, figsize=(15, 5))
        d = fits.getdata(img).astype(float)
        ref = fits.getdata(str(img).replace('.diff.', '.ref.')).astype(float)
        tgt = fits.getdata(Path(row['filepath']) / (frame.split('.optimal')[0] + '.fits')).astype(float)
        t = db.target_info(row['targetid'], conn)
        from astropy.wcs import WCS
        x, y = WCS(fits.getheader(img)).wcs_world2pix([t['ra0']], [t['dec0']], 0)
        xi, yi, s = int(x[0]), int(y[0]), 150
        for a, arr, ttl in zip(ax, (tgt, ref, d), ('target', 'registered template', 'difference')):
            cut = arr[max(yi - s, 0):yi + s, max(xi - s, 0):xi + s]
            lo, hi = _zscale(cut)
            a.imshow(cut, origin='lower', cmap='gray', vmin=lo, vmax=hi)
            a.set_title(ttl)
    elif stage == 'zcat':
        fig, ax = plt.subplots(figsize=(6, 4))
        m = qa.get('metrics', {})
        ax.text(0.02, 0.98, json.dumps(m, indent=1, default=str)[:800], va='top', family='monospace', fontsize=7,
                transform=ax.transAxes)
        ax.axis('off')
    else:
        raise ValueError(f'no packet for {stage}')
    fig.tight_layout()
    fig.savefig(out, dpi=70)
    plt.close(fig)
    q, verdicts = QUESTIONS[stage]
    side = dict(frame=frame, stage=stage, png=str(out), question=q, verdicts=verdicts,
                redo_params=sorted(REDO_PARAMS.get(stage, [])), qa=qa)
    Path(str(out).replace('.png', '.json')).write_text(json.dumps(side, indent=1, default=str))
    return out


def _summary(stage, summary=None):
    """A stage summary: the given file (e.g. a step result of ``snpipe run``) or ``qa/<stage>-latest.json``
    (which is the summary of the LAST call of that stage only)."""
    return json.loads(Path(summary or config.workdir() / 'qa' / f'{stage}-latest.json').read_text())


def diff_image_of(frame, conn=None):
    """The default difference image made from science ``frame`` (diff QA is filed under the science frame)."""
    if '.diff.' in frame:
        return frame
    rows = db.query('SELECT nameout FROM photpairing WHERE namein=?', (frame,), conn)
    names = [r['nameout'] for r in rows if not any(t in r['nameout'] for t in ('.zp.', '.cut.'))]
    return names[0] if names else None


def ensemble(stage, keys, group=('filter', 'tel'), z=3.5, conn=None, summary=None):
    """Flag frames whose metric deviates from its peers (robust z-score)."""
    s = _summary(stage, summary)
    frames = [f for f in s['frames'] if f['status'] in ('ok', 'warn')]
    flags = {}
    for k in keys:
        for f in frames:
            row = db.get_frame(f['frame'], conn)
            f['_grp'] = (row['filter'], f['frame'][3:6])
        groups = {}
        for f in frames:
            if k in f['metrics'] and isinstance(f['metrics'][k], (int, float)):
                groups.setdefault(f['_grp'], []).append(f)
        for g, fl in groups.items():
            v = np.array([f['metrics'][k] for f in fl], float)
            if len(v) < 5:
                continue
            med = np.median(v)
            mad = 1.4826 * np.median(np.abs(v - med)) or np.std(v) or 1
            for f, vi in zip(fl, v):
                if abs(vi - med) / mad > z:
                    flags.setdefault(f['frame'], []).append(f'{k}={vi:.4g} vs peers {med:.4g}+-{mad:.2g}')
    return flags


def queue(stage, sample=5, seed=0, conn=None, summary=None, name=None):
    """Review queue of one stage summary: every warn/fail frame + ``sample`` random ok frames, with packets.
    Written to ``review/<name or stage>/queue.json``; returns its path."""
    s = _summary(stage, summary)
    frames = s.get('frames', [])
    status = {f['frame']: f['status'] for f in frames}
    messages = {f['frame']: '; '.join(f.get('messages', [])) for f in frames}
    todo = [f['frame'] for f in frames if f['status'] in ('warn', 'fail')]
    ok = [f['frame'] for f in frames if f['status'] == 'ok']
    random.Random(seed).shuffle(ok)
    items = []
    for fr in todo + ok[:sample]:
        target = diff_image_of(fr, conn) if stage == 'diff' else fr   # verdicts on a diff name the diff image
        try:
            if target is None:
                raise FileNotFoundError('no difference image')
            p = str(packet(stage, target, conn))
        except Exception as e:  # products missing for failed frames
            p = f'unavailable: {e}'
        items.append(dict(frame=target or fr, science_frame=fr if stage == 'diff' else None, status=status[fr],
                          messages=messages[fr], packet=p, reason='spot check' if fr in ok else 'warn/fail'))
    out = _rdir(name or stage) / 'queue.json'
    out.write_text(json.dumps(dict(stage=stage, summary=str(summary or 'qa/latest'), question=QUESTIONS[stage][0],
                                   verdicts=QUESTIONS[stage][1], items=items), indent=1))
    return out


def verdict(frame, stage, v, reason, params=None, who='agent', conn=None):
    """Apply a review verdict with the same DB effects as the old interactive answers."""
    allowed = QUESTIONS[stage][1]
    if v not in allowed:
        raise ValueError(f'{v!r} not allowed for {stage}: {sorted(allowed)}')
    params = params or {}
    bad = set(params) - REDO_PARAMS.get(stage, set())
    if bad:
        raise ValueError(f'parameters {sorted(bad)} are not remediation knobs for {stage}')
    row = db.get_frame(frame, conn)
    if v == 'bad':
        db.update(frame, conn, quality=1)
    elif v == 'redo' and stage == 'psf':
        db.update(frame, conn, psf='X', psfmag=9999)
    elif v == 'redo' and stage == 'wcs':
        db.update(frame, conn, wcs=9999, psf='X', psfmag=9999)
    elif v == 'redo' and stage == 'zcat':
        db.update(frame, conn, zcat='X')
    elif v in ('redo', 'delete') and stage in ('psfmag', 'getmag'):
        db.update(frame, conn, psfmag=9999, psfdmag=9999, apmag=9999, dapmag=9999, mag=9999, dmag=9999)
    elif v == 'ulim':
        db.update(frame, conn, magtype=-1)
    elif v == 'delete' and stage == 'diff':
        # only a difference-image product may be deleted. The diff QA/review queue is keyed by the science frame,
        # and globbing '<science stem>*' removed the raw science image and all its products (bugs.md B14).
        if '.diff.' not in frame:
            raise ValueError(f'{frame} is not a difference image: give the .diff.fits name, not the science frame')
        p = Path(row['filepath']) / frame
        for f in p.parent.glob(frame[:-len('.fits')] + '.*'):
            f.unlink()
        with (conn or db.connect()):
            (conn or db.connect()).execute('DELETE FROM photlco WHERE filename=?', (frame,))
    rec = dict(time=time.strftime('%Y-%m-%dT%H:%M:%S'), who=who, frame=frame, stage=stage, verdict=v,
               reason=reason, params=params)
    log = config.workdir() / 'review' / 'verdicts.jsonl'
    log.parent.mkdir(exist_ok=True)
    with open(log, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')
    if v == 'redo' and params:
        knobs = config.workdir() / 'review' / 'redo_params.json'
        d = json.loads(knobs.read_text()) if knobs.exists() else {}
        d.setdefault(stage, {})[frame] = params
        knobs.write_text(json.dumps(d, indent=1))
    return rec


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
        if not isinstance(s, dict) or not s.get('frames') or s.get('stage') not in QUESTIONS:
            continue
        try:
            q = queue(s['stage'], sample=sample, summary=f, name=f.stem)
            items = json.loads(q.read_text())['items']
            queues[f.stem] = dict(stage=s['stage'], queue=str(q), n_items=len(items),
                                  n_warn_fail=sum(i['reason'] == 'warn/fail' for i in items))
        except Exception as e:
            queues[f.stem] = dict(stage=s['stage'], error=f'{type(e).__name__}: {e}')
    Path(output).write_text(json.dumps(queues, indent=1))
    return queues
