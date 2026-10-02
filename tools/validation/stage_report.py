"""Stage-by-stage visual report: for every stage, old vs new (left) and how the agent checks it (right).

usage: python tools/validation/stage_report.py --old-run OLD --new-run NEW --old-csv photlco_old.tsv --old-seepsf DIR
                                    --out docs/validation/sn2024pxl/stages
Figures come only from products on disk: the two databases, per-frame ``*.qa.json`` files and FITS products.
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.wcs import WCS  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / 'src'))
from compare import COLORS, FILT  # noqa: E402
from visual_compare import load, pairs, zs  # noqa: E402

RA, DEC = 263.113958, 7.062411
C_OLD, C_NEW, C_OK, C_WARN, C_FAIL = '#9a9a9a', '#0b6e99', '#2a9d3a', '#e09b00', '#c0392b'
plt.rcParams.update({'font.size': 8.5, 'axes.titlesize': 9, 'axes.spines.top': False, 'axes.spines.right': False})


def qa_records(new_run, stage, diff):
    out = []
    for f in glob.glob(str(Path(new_run) / 'data' / '*' / '*' / f'*.{stage}.qa.json')):
        if ('.diff.' in Path(f).name) != diff or any(t in Path(f).name for t in ('.zp.', '.cut.')):
            continue
        try:
            out.append(json.load(open(f)))
        except ValueError:
            pass
    return out


def stamp(ax, a, title, cmap='gray', v=None):
    lo, hi = v or zs(a)
    ax.imshow(a, origin='lower', cmap=cmap, vmin=lo, vmax=hi, interpolation='nearest')
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(True)


def one_to_one(ax, axr, p, label, failed=None):
    bad = [q for q in p if failed and q[4] in failed]
    p = [q for q in p if not (failed and q[4] in failed)]
    x, y = np.array([q[1] for q in p]), np.array([q[2] for q in p])
    for f in FILT:
        s = np.array([q[0] == f for q in p])
        if s.any():
            ax.plot(x[s], y[s], 'o', ms=3, color=COLORS[FILT[f]], label=FILT[f])
            axr.plot(x[s], y[s] - x[s], 'o', ms=3, color=COLORS[FILT[f]])
    lim = [np.nanmin(np.r_[x, y]), np.nanmax(np.r_[x, y])]
    ax.plot(lim, lim, 'k-', lw=0.6)
    if bad:
        bx, by = np.array([q[1] for q in bad]), np.array([q[2] for q in bad])
        ax.plot(bx, np.clip(by, lim[0] - 0.3, lim[1] + 0.3), 'x', color=C_FAIL, ms=6, mew=1.5,
                label=f'QA fail, not in light curve ({len(bad)})')
        ax.set_ylim(lim[0] - 0.5, lim[1] + 0.5)
    d = y - x
    rs = 1.4826 * np.median(np.abs(d - np.median(d)))
    ax.set_title(f'{label}\nnew − old: {np.median(d):+.3f} ± {rs:.3f} (n={len(d)}{", QA-passed" if failed else ""})')
    ax.set_ylabel('new')
    ax.tick_params(labelbottom=False)
    axr.axhline(0, color='k', lw=0.6)
    w = max(0.05, 5 * rs)
    axr.set_ylim(-w, w)
    axr.set_ylabel('new − old')
    axr.set_xlabel('old')
    ax.legend(fontsize=6.5, ncol=5, frameon=False, loc='upper left', handletextpad=0.1, columnspacing=0.6)


def gate_hist(ax, v, gates, xlabel, title, log=False, colors=None, bins=40):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not np.isscalar(bins):
        b = bins
    elif log:
        v = v[v > 0]
        b = np.logspace(np.log10(v.min()) - 0.1, np.log10(max(v.max(), max(g for g, _ in gates))) + 0.1, bins)
        ax.set_xscale('log')
    if log:
        ax.set_xscale('log')
    if np.isscalar(bins) and not log:
        lo = min(v.min(), min(g for g, _ in gates))
        hi = max(v.max(), max(g for g, _ in gates))
        pad = 0.05 * (hi - lo)
        b = np.linspace(lo - pad, hi + pad, bins)
    if colors is None:
        ax.hist(v, bins=b, color=C_NEW, alpha=0.85)
    else:
        ax.hist([np.asarray(vv, float)[np.isfinite(np.asarray(vv, float))] for vv, _ in colors.values()], bins=b,
                color=[c for _, c in colors.values()], label=list(colors), stacked=True)
        ax.legend(fontsize=7, frameon=False, loc='upper left', bbox_to_anchor=(0.0, -0.22), ncol=1)
    for g, lab in gates:
        ax.axvline(g, color=C_FAIL, ls='--', lw=1)
        ax.text(g, ax.get_ylim()[1] * 0.97, ' ' + lab, color=C_FAIL, fontsize=7, va='top', rotation=90, ha='right')
    ax.set_xlabel(xlabel)
    ax.set_ylabel('frames')
    ax.set_title(title)


def save(fig, out, name):
    fig.savefig(out / f'{name}.png', dpi=130, bbox_inches='tight')
    plt.close(fig)


# ---------------------------------------------------------------- stages
def fig_cosmic(a, out, old, new):
    fr = 'cpt1m012-fa06-20240723-0133-e91'
    d = Path(a.new_run) / 'data/lsc/20240723'
    od = Path(a.old_run) / 'data/lsc/20240723'
    img = fits.getdata(d / f'{fr}.fits').astype(float)
    mo = fits.getdata(od / f'{fr}.mask.fits') > 0
    mn = fits.getdata(d / f'{fr}.mask.fits') > 0
    # the 160x160 box with most cosmic-ray pixels
    s = 160
    k = np.add.reduceat(np.add.reduceat(mn.astype(int), np.arange(0, mn.shape[0], s), 0), np.arange(0, mn.shape[1], s), 1)
    iy, ix = np.unravel_index(np.argmax(k), k.shape)
    sl = (slice(iy * s, iy * s + s), slice(ix * s, ix * s + s))
    fig = plt.figure(figsize=(12, 3.0))
    gs = fig.add_gridspec(1, 5, width_ratios=[1, 1, 1, 1, 1.5], wspace=0.15)
    stamp(fig.add_subplot(gs[0]), img[sl], 'image (160×160 px)')
    stamp(fig.add_subplot(gs[1]), mo[sl], 'old mask', 'Greys', (0, 1))
    stamp(fig.add_subplot(gs[2]), mn[sl], 'new mask', 'Greys', (0, 1))
    stamp(fig.add_subplot(gs[3]), (mo ^ mn)[sl], f'pixels that differ: {int((mo ^ mn).sum())}\n(whole frame)', 'Reds', (0, 1))
    recs = qa_records(a.new_run, 'cosmic', False)
    ax = fig.add_subplot(gs[4])
    gate_hist(ax, [r['metrics'].get('cr_fraction', np.nan) for r in recs], [(0.01, 'warn > 1 %')],
              'fraction of pixels flagged', f'agent check: {len(recs)} frames', log=True)
    save(fig, out, 'cosmic')
    return dict(n=len(recs), differ=int((mo ^ mn).sum()))


def fig_wcs(a, out, old, new):
    recs = [r for r in qa_records(a.new_run, 'wcs', False) if r['metrics']]
    fig, ax = plt.subplots(1, 2, figsize=(8.5, 3.0))
    rms = np.array([r['metrics']['rms_arcsec'] for r in recs])
    off = np.array([r['metrics']['offset_arcsec'] for r in recs])
    nm = np.array([r['metrics']['n_match'] for r in recs])
    ax[0].axvspan(0, 2.0, color=C_OK, alpha=0.08)
    ax[0].axhspan(0, 1.0, color=C_OK, alpha=0.08)
    ax[0].scatter(rms, off, c=C_NEW, s=18)
    ax[0].axvline(2.0, color=C_FAIL, ls='--')
    ax[0].axhline(1.0, color=C_FAIL, ls='--')
    ax[0].set_xlim(0, 2.4)
    ax[0].set_ylim(0, 1.2)
    ax[0].set_xlabel('rms of Gaia match ["]  (gate 2")')
    ax[0].set_ylabel('median offset ["]  (gate 1")')
    ax[0].set_title(f'agent check: WCS vs Gaia DR3 ({len(recs)} frames)')
    ax[1].hist(nm, bins=15, color=C_NEW)
    ax[1].axvline(10, color=C_FAIL, ls='--')
    ax[1].set_xlabel('matched Gaia stars (gate ≥ 10)')
    ax[1].set_ylabel('frames')
    ax[1].set_title('old pipeline: no check (human checkwcs)')
    fig.tight_layout()
    save(fig, out, 'wcs')
    return dict(n=len(recs), rms_med=float(np.median(rms)))


def fig_psf(a, out, old, new):
    from snpipe.psf import PSFModel
    fig = plt.figure(figsize=(13, 3.4))
    gs = fig.add_gridspec(2, 6, width_ratios=[1, 1, 1, 0.25, 1.6, 1.6], height_ratios=[3, 1], wspace=0.4, hspace=0.08)
    po = Path(a.old_seepsf) / 'old_psf_cpt0133.fits'
    pn = Path(a.new_run) / 'data/lsc/20240723/cpt1m012-fa06-20240723-0133-e91.psf.fits'
    A = fits.getdata(po).astype(float)
    B = PSFModel.read(pn).image()
    n = min(A.shape[0], B.shape[0])
    ca, cb = (A.shape[0] - n) // 2, (B.shape[0] - n) // 2
    A, B = A[ca:ca + n, ca:ca + n], B[cb:cb + n, cb:cb + n]
    A, B = A / A.sum(), B / B.sum()
    stamp(fig.add_subplot(gs[:, 0]), A, 'old PSF (IRAF)', 'viridis', (0, A.max()))
    stamp(fig.add_subplot(gs[:, 1]), B, 'new PSF (photutils)', 'viridis', (0, A.max()))
    stamp(fig.add_subplot(gs[:, 2]), (B - A) / A.max(), f'(new − old)/peak\nmax {np.abs(B - A).max() / A.max():.1%}',
          'RdBu_r', (-0.05, 0.05))
    p = pairs(old, new, 'apercorr', 1, None, -0.3, 0.3)
    one_to_one(fig.add_subplot(gs[0, 4]), fig.add_subplot(gs[1, 4]), p, 'aperture correction')
    # agent: |apco| gate over all science frames; frames the old pipeline lost
    ax = fig.add_subplot(gs[:, 5])
    v_all, v_rec = [], []
    for fn, r in new.items():
        if r['filetype'] != 1 or r['apercorr'] is None or r['psf'] == 'X':
            continue
        v = float(r['apercorr'])
        o = old.get(fn)
        # the old pipeline was run on 2024-07-22..28 only; there a missing aperture correction = its psf stage failed
        lost = (o is not None and '20240722' <= str(o['dateobs']).replace('-', '')[:8] <= '20240728'
                and str(o.get('apercorr')) in ('None', '', 'NULL', 'nan'))
        (v_rec if lost else v_all).append(v)
    gate_hist(ax, v_all + v_rec, [(-0.1, '|apco| > 0.1 → ladder'), (0.1, '')], 'aperture correction (new, all frames)',
              f'agent check: {len(v_all) + len(v_rec)} frames pass', colors={
                  'passed': (v_all, C_NEW), f'old pipeline failed, ladder fixed ({len(v_rec)})': (v_rec, C_WARN)},
              bins=np.linspace(-0.15, 0.15, 31))
    save(fig, out, 'psf')
    # remediation ladder of a frame that stayed failed
    lad = [r for r in qa_records(a.new_run, 'psf', False) if r['status'] == 'fail' and 'attempts' in r['metrics']]
    lad_info = []
    if lad:
        r = lad[0]
        att = r['metrics']['attempts']
        fig, ax = plt.subplots(figsize=(6.5, 2.4))
        vals = [abs(t['metrics'].get('apco', np.nan)) if t.get('metrics') else np.nan for t in att]
        labs = [t['label'] for t in att]
        ax.barh(range(len(att)), np.nan_to_num(vals, nan=0), color=[C_FAIL if t['status'] == 'fail' else C_OK for t in att])
        ax.axvline(0.1, color='k', ls='--', lw=0.8)
        ax.set_yticks(range(len(att)), labs)
        ax.invert_yaxis()
        ax.set_xscale('log')
        ax.set_xlabel('|aperture correction| per attempt (gate 0.1)')
        ax.set_title(f"remediation ladder, {r['frame'][:30]}: all attempts fail → review packet", fontsize=8.5)
        fig.tight_layout()
        save(fig, out, 'psf_ladder')
        lad_info = labs
    return dict(n=len(v_all) + len(v_rec), recovered=len(v_rec), ladder=lad_info)


def fig_psfmag(a, out, old, new):
    fr = 'cpt1m012-fa06-20240723-0133-e91.fits'
    po, pn = Path(old[fr]['filepath']) / fr, Path(new[fr]['filepath']) / fr
    fig = plt.figure(figsize=(13, 3.4))
    gs = fig.add_gridspec(2, 7, width_ratios=[1, 1, 1, 1, 0.2, 1.6, 1.6], height_ratios=[3, 1], wspace=0.45, hspace=0.08)
    og_o, rs_o = (fits.getdata(str(po).replace('.fits', e)) for e in ('.og.fits', '.rs.fits'))
    og_n, rs_n = (fits.getdata(str(pn).replace('.fits', e)) for e in ('.og.fits', '.rs.fits'))
    v, rv = zs(og_n), zs(rs_n)
    stamp(fig.add_subplot(gs[:, 0]), og_o, 'old: SN stamp', v=v)
    stamp(fig.add_subplot(gs[:, 1]), rs_o, 'old: after PSF fit', v=rv)
    stamp(fig.add_subplot(gs[:, 2]), og_n, 'new: SN stamp', v=v)
    stamp(fig.add_subplot(gs[:, 3]), rs_n, 'new: after PSF fit', v=rv)
    p = pairs(old, new, 'psfmag', 1, 'psfdmag', -20, 5)
    one_to_one(fig.add_subplot(gs[0, 5]), fig.add_subplot(gs[1, 5]), p, 'SN PSF magnitude (instrumental)')
    recs = [r for r in qa_records(a.new_run, 'psfmag', False) if r['metrics'].get('recenter_shift_pix') is not None]
    ax = fig.add_subplot(gs[:, 6])
    sh = np.array([r['metrics']['recenter_shift_pix'] / r['thresholds']['recenter_shift_pix'][1] for r in recs])
    sp = np.array([max(r['metrics'].get('iteration_spread', 0), 1e-4) for r in recs])
    col = [C_FAIL if r['status'] == 'fail' else C_WARN if r['status'] == 'warn' else C_NEW for r in recs]
    ax.add_patch(plt.Rectangle((0, 1e-4), 1, 0.05, color=C_OK, alpha=0.08))
    ax.scatter(sh, sp, c=col, s=9)
    ax.axvline(1, color=C_FAIL, ls='--')
    ax.axhline(0.05, color=C_FAIL, ls='--')
    ax.set_yscale('log')
    ax.set_xlabel('recentring shift / allowed (gate 1)')
    ax.set_ylabel('iteration spread [mag] (gate 0.05)')
    nw = sum(r['status'] == 'warn' for r in recs)
    ax.set_xscale('symlog', linthresh=1)
    ax.set_xlim(0, None)
    ax.set_title(f'agent check: {len(recs)} frames\n{nw} warn → review packet')
    save(fig, out, 'psfmag')
    return dict(n=len(recs), warn=nw)


def fig_zcat(a, out, old, new):
    fig = plt.figure(figsize=(9.5, 3.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[3, 1], wspace=0.3, hspace=0.08)
    p = pairs(old, new, 'z1', 1, 'dz1', 15, 30)
    one_to_one(fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0]), p, 'zero point (unsubtracted frames)')
    recs = qa_records(a.new_run, 'zcat', False) + qa_records(a.new_run, 'zcat', True)
    nk = [min(v for k, v in r['metrics'].items() if k.startswith('nkeep_')) for r in recs
          if any(k.startswith('nkeep_') for k in r['metrics'])]
    ax = fig.add_subplot(gs[:, 1])
    gate_hist(ax, nk, [(5, 'warn < 5 stars')], 'calibration stars kept after clipping',
              f'agent check: {len(nk)} frames', log=True)
    save(fig, out, 'zcat')
    return dict(n=len(nk))


def fig_diff(a, out, old, new):
    fr = 'cpt1m012-fa06-20240723-0133-e91.fits'
    d = fr.replace('.fits', '.optimal.fl.diff.fits')
    fo, fn = Path(old[d]['filepath']) / d, Path(new[d]['filepath']) / d
    do, dn = fits.getdata(fo).astype(float), fits.getdata(fn).astype(float)
    x, y = WCS(fits.getheader(fn)).wcs_world2pix([RA], [DEC], 0)
    xi, yi, s = int(x[0]), int(y[0]), 50
    sl = (slice(yi - s, yi + s), slice(xi - s, xi + s))
    sci = fits.getdata(Path(new[fr]['filepath']) / fr).astype(float)[sl]
    ref = fits.getdata(str(fn).replace('.diff.fits', '.ref.fits')).astype(float)[sl]
    fig = plt.figure(figsize=(13, 3.0))
    gs = fig.add_gridspec(1, 6, width_ratios=[1, 1, 1, 1, 0.15, 1.7], wspace=0.15)
    v = zs(dn[sl])
    stamp(fig.add_subplot(gs[0]), sci, 'science (2024)')
    stamp(fig.add_subplot(gs[1]), ref, 'template (2018), registered')
    stamp(fig.add_subplot(gs[2]), do[sl], 'old difference', v=v)
    stamp(fig.add_subplot(gs[3]), dn[sl], 'new difference', v=v)
    # the gate (noise of difference / noise of registered template) was added while this batch ran:
    # recompute it from the products for every difference image (robust sigma on a 4x subsampled grid)
    vals = []
    for r in new.values():
        if r['filetype'] != 3:
            continue
        pd_ = Path(r['filepath']) / r['filename']
        pr = Path(str(pd_).replace('.diff.fits', '.ref.fits'))
        if not pr.exists():
            continue
        sig = []
        for q in (pd_, pr):
            with fits.open(q, memmap=True) as h:  # central 1024x1024 block only (reads 1/16 of the file)
                ny, nx = h[0].shape
                x = h[0].section[ny // 2 - 512:ny // 2 + 512, nx // 2 - 512:nx // 2 + 512].astype(float)
                x = x[np.isfinite(x) & (x != 0)]
                sig.append(1.4826 * np.median(np.abs(x - np.median(x))))
        vals.append(sig[0] / sig[1])
    recs = vals
    ax = fig.add_subplot(gs[5])
    gate_hist(ax, vals, [(5, 'warn > 5'), (10, 'fail > 10')], 'noise of difference / noise of template\n(central 1024² px)',
              f'agent check: {len(recs)} differences', log=True)
    save(fig, out, 'diff')
    return dict(n=len(recs), fail=int(sum(np.array(vals) > 10)), warn=int(sum((np.array(vals) > 5) & (np.array(vals) <= 10))))


def fig_mag(a, out, old, new):
    fig = plt.figure(figsize=(9.5, 3.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[3, 1], wspace=0.3, hspace=0.08)
    from snpipe.getmag import qa_failed
    p = pairs(old, new, 'mag', 3, 'dmag', 10, 25)
    failed = {fn for fn, r in new.items() if r['filetype'] == 3 and qa_failed(r)}
    one_to_one(fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0]), p, 'SN calibrated mag (difference images)', failed)
    recs = [r for r in qa_records(a.new_run, 'mag', True) if r['metrics'].get('diff_minus_unsubtracted') is not None]
    v = np.array([r['metrics']['diff_minus_unsubtracted'] for r in recs])
    ax = fig.add_subplot(gs[:, 1])
    gate_hist(ax, np.clip(v, -1, 3), [(-0.2, 'fail: brighter than unsubtracted')],
              'difference mag − unsubtracted mag (clipped to [−1, 3])', f'agent check: {len(v)} frames, {int((v < -0.2).sum())} fail',
              bins=np.linspace(-1, 3, 41))
    save(fig, out, 'mag')
    return dict(n=len(v), fail=int((v < -0.2).sum()))


def fig_getmag(a, out, old, new):
    from snpipe.getmag import flag_outliers
    from astropy.table import Table
    from snpipe.getmag import qa_failed
    rows = [r for r in new.values() if r['filetype'] == 3 and r['mag'] is not None and abs(r['mag']) < 99
            and not qa_failed(r)]
    t = Table({'jd': [r['mjd'] + 2400000.5 for r in rows], 'mag': [r['mag'] for r in rows],
               'dmag': [r['dmag'] for r in rows], 'filter': [r['filter'] for r in rows]})
    t['flag'] = flag_outliers(t)
    fig, ax = plt.subplots(figsize=(9.5, 3.6))
    for f in FILT:
        s = t['filter'] == f
        if not s.any():
            continue
        c = COLORS[FILT[f]]
        ax.errorbar(t['jd'][s] - 2460500, t['mag'][s], t['dmag'][s], fmt='s', ms=3, color=c, label=FILT[f], lw=0.6)
        oo = [o for o in old.values() if int(o['filetype']) == 3 and o['filter'] == f and o['mag'] not in (None, '')
              and abs(float(o['mag'])) < 99]
        if oo:
            ax.plot([float(o['mjd']) + 2400000.5 - 2460500 for o in oo], [float(o['mag']) for o in oo], 'o', mfc='none',
                    color=c, ms=5, mew=0.7)
    fl = t['flag'] == 1
    ax.plot(t['jd'][fl] - 2460500, t['mag'][fl], 'o', ms=11, mfc='none', mec=C_FAIL, mew=1.4,
            label=f'flagged by agent ({int(fl.sum())})')
    ax.invert_yaxis()
    ax.set_xlabel('JD − 2460500')
    ax.set_ylabel('mag (difference imaging)')
    ax.set_title('light curve (QA-failed frames removed): squares = new, open circles = old (subset); red rings = flagged for review')
    ax.legend(fontsize=7, ncol=7, frameon=False, loc='lower left')
    fig.tight_layout()
    save(fig, out, 'getmag')
    return dict(n=len(t), flagged=int(fl.sum()))


def main():
    ap = argparse.ArgumentParser()
    for k in ('--old-run', '--new-run', '--old-csv', '--old-seepsf', '--out'):
        ap.add_argument(k, required=True)
    ap.add_argument('--only', nargs='*', help='stages to redo (others keep their entry in stages.json)')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    old, new = load(a)
    # option-test products (.zp = --gain zeropoint, .cut = --region cutout) are not part of the reduction
    new = {k: v for k, v in new.items() if not any(t in k for t in ('.zp.diff', '.cut.diff'))}
    sj = out / 'stages.json'
    res = json.loads(sj.read_text()) if a.only and sj.exists() else {}
    for name, fn in (('cosmic', fig_cosmic), ('wcs', fig_wcs), ('psf', fig_psf), ('psfmag', fig_psfmag),
                     ('zcat', fig_zcat), ('diff', fig_diff), ('mag', fig_mag), ('getmag', fig_getmag)):
        if a.only and name not in a.only:
            continue
        try:
            res[name] = fn(a, out, old, new)
        except Exception as e:  # keep the other stages
            res[name] = {'error': repr(e)}
        print(name, res[name])
    (out / 'stages.json').write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
