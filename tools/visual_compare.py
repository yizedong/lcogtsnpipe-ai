"""Visual old-vs-new comparisons for the report (images side by side, 1:1 plots, pulls, per-band light curves).

usage: python tools/visual_compare.py --old-run OLD --new-run NEW --old-csv photlco_old.tsv --paper union_df_table.tex
                                      --old-seepsf DIR --timing timing.json --out docs/report/visual
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.table import Table  # noqa: E402
from astropy.visualization import ZScaleInterval  # noqa: E402
from astropy.wcs import WCS  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from compare import COLORS, FILT, paper_table  # noqa: E402

plt.rcParams.update({'font.size': 9, 'axes.titlesize': 9})


def zs(a):
    a = a[np.isfinite(a)]
    return ZScaleInterval().get_limits(a) if a.size else (0, 1)


def load(args):
    o = Table.read(args.old_csv, format='ascii.tab')
    old = {r['filename']: dict(zip(o.colnames, r)) for r in o}
    c = sqlite3.connect(Path(args.new_run) / 'snpipe.sqlite')
    c.row_factory = sqlite3.Row
    new = {r['filename']: dict(r) for r in c.execute('select * from photlco')}
    return old, new


def fig_psf(args, out):
    sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
    from snpipe.psf import PSFModel
    cases = [('cpt1m012-fa06-20240723-0133-e91', 'lsc/20240723', 'old_psf_cpt0133.fits', '1 m (cpt), B'),
             ('ogg0m455-sq30-20240725-0180-e91', '0m4/20240725', 'old_psf_ogg0180.fits', '0.4 m (ogg), V'),
             ('elp1m008-fl05-20180306-0091-e91.temp', 'lsc/20180306', 'old_psf_temp0091.fits', 'template (elp 1 m), r')]
    fig, ax = plt.subplots(len(cases), 4, figsize=(13, 3.2 * len(cases)))
    for i, (stem, d, oldimg, lab) in enumerate(cases):
        po = Path(args.old_seepsf) / oldimg
        pn = Path(args.new_run) / 'data' / d / (stem + '.psf.fits')
        if not po.exists() or not pn.exists():
            continue
        a = fits.getdata(po).astype(float)
        b = PSFModel.read(pn).image()
        n = min(a.shape[0], b.shape[0])
        ca, cb = (a.shape[0] - n) // 2, (b.shape[0] - n) // 2
        a, b = a[ca:ca + n, ca:ca + n], b[cb:cb + n, cb:cb + n]
        a, b = a / a.sum(), b / b.sum()
        vmax = a.max()
        ax[i, 0].imshow(a, origin='lower', vmax=vmax)
        ax[i, 0].set_title(f'{lab}: old (IRAF seepsf)')
        ax[i, 1].imshow(b, origin='lower', vmax=vmax)
        ax[i, 1].set_title('new (photutils, DAOPHOT recipe)')
        im = ax[i, 2].imshow((b - a) / vmax, origin='lower', cmap='RdBu_r', vmin=-0.05, vmax=0.05)
        ax[i, 2].set_title('(new − old) / old peak')
        plt.colorbar(im, ax=ax[i, 2], fraction=0.046)
        r = np.hypot(*np.meshgrid(np.arange(n) - n // 2, np.arange(n) - n // 2))
        ax[i, 3].plot(r.ravel(), a.ravel() / vmax, '.', ms=2, label='old', color='0.5')
        ax[i, 3].plot(r.ravel(), b.ravel() / vmax, '.', ms=2, label='new', color='C3', alpha=0.6)
        ax[i, 3].set_xlim(0, n // 2)
        ax[i, 3].set_title('radial profile (normalised)')
        ax[i, 3].legend(fontsize=7)
        for k in range(3):
            ax[i, k].set_xticks([])
            ax[i, k].set_yticks([])
    fig.tight_layout()
    fig.savefig(out / 'psf_models.png', dpi=100)
    plt.close(fig)


def fig_diff(args, out, old, new, frames):
    fig, ax = plt.subplots(len(frames), 4, figsize=(13, 3.3 * len(frames)))
    ax = np.atleast_2d(ax)
    for i, fr in enumerate(frames):
        d = fr.replace('.fits', '.optimal.fl.diff.fits')
        if d not in old or d not in new:
            continue
        fo, fn = Path(old[d]['filepath']) / d, Path(new[d]['filepath']) / d
        do, ho = fits.getdata(fo).astype(float), fits.getheader(fo)
        dn, hn = fits.getdata(fn).astype(float), fits.getheader(fn)
        t = np.loadtxt  # noqa
        ra, dec = 263.113958, 7.062411
        x, y = WCS(hn).wcs_world2pix([ra], [dec], 0)
        xi, yi, s = int(x[0]), int(y[0]), 60
        co, cn = do[yi - s:yi + s, xi - s:xi + s], dn[yi - s:yi + s, xi - s:xi + s]
        tgt = fits.getdata(Path(new[fr]['filepath']) / fr).astype(float)[yi - s:yi + s, xi - s:xi + s]
        lo, hi = zs(cn)
        ax[i, 0].imshow(tgt, origin='lower', cmap='gray', vmin=zs(tgt)[0], vmax=zs(tgt)[1])
        ax[i, 0].set_title(f"{fr[:24]} {new[fr]['filter']}: science")
        ax[i, 1].imshow(co, origin='lower', cmap='gray', vmin=lo, vmax=hi)
        ax[i, 1].set_title('old difference (IRAF + PyZOGY)')
        ax[i, 2].imshow(cn, origin='lower', cmap='gray', vmin=lo, vmax=hi)
        ax[i, 2].set_title('new difference')
        sig = 1.4826 * np.nanmedian(np.abs(cn - np.nanmedian(cn)))
        im = ax[i, 3].imshow((cn - co) / sig, origin='lower', cmap='RdBu_r', vmin=-3, vmax=3)
        ax[i, 3].set_title('(new − old) / σ(new)')
        plt.colorbar(im, ax=ax[i, 3], fraction=0.046)
        for k in range(4):
            ax[i, k].set_xticks([])
            ax[i, k].set_yticks([])
            ax[i, k].plot([s], [s], '+', color='C1', ms=10)
    fig.tight_layout()
    fig.savefig(out / 'difference_images.png', dpi=100)
    plt.close(fig)


def fig_snfit(args, out, old, new, frames):
    fig, ax = plt.subplots(len(frames), 4, figsize=(12, 3.1 * len(frames)))
    ax = np.atleast_2d(ax)
    for i, fr in enumerate(frames):
        po, pn = Path(old[fr]['filepath']) / fr, Path(new[fr]['filepath']) / fr
        try:
            og_o, rs_o = fits.getdata(str(po).replace('.fits', '.og.fits')), fits.getdata(str(po).replace('.fits', '.rs.fits'))
            og_n, rs_n = fits.getdata(str(pn).replace('.fits', '.og.fits')), fits.getdata(str(pn).replace('.fits', '.rs.fits'))
        except FileNotFoundError:
            continue
        lo, hi = zs(og_n)
        rlo, rhi = zs(rs_n)
        for k, (a, t, v) in enumerate(((og_o, 'old: original stamp', (lo, hi)), (rs_o, 'old: residual after PSF fit', (rlo, rhi)),
                                        (og_n, 'new: original stamp', (lo, hi)), (rs_n, 'new: residual after PSF fit', (rlo, rhi)))):
            ax[i, k].imshow(a, origin='lower', cmap='gray', vmin=v[0], vmax=v[1])
            ax[i, k].set_title(t if k else f"{fr[:24]} {new[fr]['filter']}  " + t)
            ax[i, k].set_xticks([])
            ax[i, k].set_yticks([])
        ax[i, 0].text(0.02, 0.02, f"psfmag {float(old[fr]['psfmag']):.3f}", transform=ax[i, 0].transAxes, color='y', fontsize=8)
        ax[i, 2].text(0.02, 0.02, f"psfmag {float(new[fr]['psfmag']):.3f}", transform=ax[i, 2].transAxes, color='y', fontsize=8)
    fig.tight_layout()
    fig.savefig(out / 'sn_psf_fit_stamps.png', dpi=100)
    plt.close(fig)


def pairs(old, new, col, ft, err=None, lo=None, hi=None):
    out = []
    for fn, o in old.items():
        n = new.get(fn)
        if n is None or int(o['filetype']) != ft:
            continue
        try:
            a, b = float(o[col]), float(n[col])
        except (TypeError, ValueError):
            continue
        if not (abs(a) < 99 and abs(b) < 99) or (lo is not None and not (lo < a < hi)):
            continue
        e = None
        if err:
            try:
                e = float(np.hypot(float(o[err]), float(n[err])))
            except (TypeError, ValueError):
                e = None
        out.append((o['filter'], a, b, e))
    return out


def fig_one_to_one(out, old, new):
    panels = [('apercorr', 1, None, 'aperture correction (PSF stage)', -0.3, 0.3),
              ('z1', 1, 'dz1', 'zero point z1 (unsubtracted)', 15, 30),
              ('psfmag', 1, 'psfdmag', 'SN PSF instrumental mag (unsubtracted)', -20, 5),
              ('mag', 1, 'dmag', 'SN calibrated mag (unsubtracted, PSF)', 10, 25),
              ('apmag', 3, 'dapmag', 'SN aperture instrumental mag (difference)', -20, 5),
              ('mag', 3, 'dmag', 'SN calibrated mag (difference images)', 10, 25)]
    fig = plt.figure(figsize=(13, 9.6))
    gs = fig.add_gridspec(5, 3, height_ratios=[3, 1, 0.9, 3, 1], hspace=0.08, wspace=0.28)
    pulls = {}
    for k, (col, ft, err, title, lo, hi) in enumerate(panels):
        r0, c0 = (k // 3) * 3, k % 3
        a1 = fig.add_subplot(gs[r0, c0])
        a2 = fig.add_subplot(gs[r0 + 1, c0], sharex=a1)
        p = pairs(old, new, col, ft, err, lo, hi)
        if not p:
            continue
        x, y = np.array([q[1] for q in p]), np.array([q[2] for q in p])
        for f in FILT:
            s = np.array([q[0] == f for q in p])
            if s.any():
                a1.plot(x[s], y[s], 'o', ms=3, color=COLORS[FILT[f]], label=FILT[f])
                a2.plot(x[s], y[s] - x[s], 'o', ms=3, color=COLORS[FILT[f]])
        lims = [np.nanmin(np.r_[x, y]), np.nanmax(np.r_[x, y])]
        a1.plot(lims, lims, 'k-', lw=0.6)
        a1.set_title(f'{title}  (n={len(p)})')
        a1.set_ylabel('new')
        a1.tick_params(labelbottom=False)
        a2.axhline(0, color='k', lw=0.6)
        d = y - x
        lim = max(0.05, 4 * 1.4826 * np.median(np.abs(d - np.median(d))))
        a2.set_ylim(-lim, lim)
        a2.set_ylabel('new−old')
        a2.set_xlabel('old')
        if k == 0:
            a1.legend(fontsize=7, ncol=5)
        e = np.array([q[3] if q[3] else np.nan for q in p])
        if np.isfinite(e).any():
            pulls[title] = (d / e)[np.isfinite(e) & (e > 0)]
    fig.savefig(out / 'one_to_one.png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    fig, ax = plt.subplots(1, len(pulls), figsize=(3.2 * len(pulls), 3), squeeze=False)
    for a, (t, v) in zip(ax[0], pulls.items()):
        v = v[np.abs(v) < 10]
        a.hist(v, bins=np.linspace(-5, 5, 41), color='C0', alpha=0.8)
        a.axvline(0, color='k', lw=0.6)
        a.set_title(t, fontsize=7)
        a.set_xlabel('(new − old) / combined error')
        a.text(0.03, 0.9, f'median {np.median(v):+.2f}\nrobust σ {1.4826 * np.median(np.abs(v - np.median(v))):.2f}',
               transform=a.transAxes, fontsize=7, va='top')
    fig.tight_layout()
    fig.savefig(out / 'pulls.png', dpi=100)
    plt.close(fig)


def fig_lc(out, old, new, paper):
    fig, ax = plt.subplots(2, 5, figsize=(16, 6), sharex='col', gridspec_kw=dict(height_ratios=[2.2, 1]))
    for k, f in enumerate('BgVri'):
        pf = paper[paper['filter'] == f]
        ax[0, k].plot(pf['jd'] - 2460000, pf['mag'], '-', color='0.6', lw=1, label='Singh et al.')
        ax[0, k].errorbar(pf['jd'] - 2460000, pf['mag'], pf['dmag'], fmt='.', color='0.6', ms=3)
        for lab, rows, mk, mfc in (('old', old, 'o', 'none'), ('new', new, 's', None)):
            pts = [(float(r['mjd']) + 2400000.5, float(r['mag']), float(r['dmag'])) for r in rows.values()
                   if int(r['filetype']) == 3 and FILT.get(r['filter']) == f and float(r['mag']) < 99 and float(r['dmag']) < 1]
            if not pts:
                continue
            p = np.array(pts)
            ax[0, k].errorbar(p[:, 0] - 2460000, p[:, 1], p[:, 2], fmt=mk, ms=4, color=COLORS[f], mfc=mfc or COLORS[f],
                              lw=0.8, label=lab)
            d = []
            for j, m, e in p:
                i = np.argmin(np.abs(pf['jd'] - j))
                if abs(pf['jd'][i] - j) < 0.02:
                    d.append((j, m - pf['mag'][i], np.hypot(e, pf['dmag'][i])))
            if d:
                d = np.array(d)
                ax[1, k].errorbar(d[:, 0] - 2460000, d[:, 1], d[:, 2], fmt=mk, ms=4, color=COLORS[f], mfc=mfc or COLORS[f], lw=0.8)
        ax[0, k].invert_yaxis()
        ax[0, k].set_title(f)
        ax[1, k].axhline(0, color='k', lw=0.6)
        ax[1, k].set_ylim(-0.25, 0.25)
        ax[1, k].set_xlabel('JD − 2460000')
        if k == 0:
            ax[0, k].set_ylabel('mag')
            ax[1, k].set_ylabel('pipeline − paper')
            ax[0, k].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / 'lightcurves_by_band.png', dpi=100)
    # zoom on the subset epochs where both pipelines exist
    for a in ax.ravel():
        a.set_xlim(514.5, 521.5)
    fig.savefig(out / 'lightcurves_by_band_subset.png', dpi=100)
    plt.close(fig)


def fig_timing(out, timing):
    st = list(timing)
    o = [timing[s].get('old', np.nan) for s in st]
    n = [timing[s].get('new', np.nan) for s in st]
    y = np.arange(len(st))
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(st) + 1))
    ax.barh(y + 0.2, o, 0.4, label='old (lcogtsnpipe + IRAF, serial)', color='0.6')
    ax.barh(y - 0.2, n, 0.4, label='new (snpipe)', color='C0')
    ax.set_yticks(y, st)
    ax.set_xscale('log')
    ax.set_xlabel('seconds per frame (wall clock / frames)')
    ax.invert_yaxis()
    ax.legend(fontsize=8)
    for yi, (a, b) in enumerate(zip(o, n)):
        if a and b and np.isfinite(a) and np.isfinite(b):
            ax.text(max(a, b) * 1.15, yi, f'{a / b:.1f}×', va='center', fontsize=8)
    fig.tight_layout()
    fig.savefig(out / 'timing.png', dpi=100)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    for k in ('--old-run', '--new-run', '--old-csv', '--paper', '--old-seepsf', '--timing', '--out'):
        ap.add_argument(k, required=k in ('--old-run', '--new-run', '--old-csv', '--out'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    old, new = load(a)
    if a.old_seepsf:
        fig_psf(a, out)
    frames = ['cpt1m012-fa06-20240723-0133-e91.fits', 'lsc1m009-fa04-20240726-0137-e91.fits',
              'tfn0m436-sq33-20240727-0181-e91.fits']
    fig_diff(a, out, old, new, frames)
    fig_snfit(a, out, old, new, [f for f in frames if f in old and f in new])
    fig_one_to_one(out, old, new)
    if a.paper:
        fig_lc(out, old, new, paper_table(a.paper))
    if a.timing:
        fig_timing(out, json.loads(Path(a.timing).read_text()))
    print('figures in', out)


if __name__ == '__main__':
    main()
