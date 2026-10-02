"""Stage-by-stage comparison of the old (lcogtsnpipe) and new (snpipe) reductions + the published LC.

usage: python tools/compare.py --old-run OLD_LCOSNDIR --old-csv photlco_old.csv --new-run NEW_SNPIPE_DIR
                               --paper notes/paper2024pxl/union_df_table.tex --out docs/report
The old photlco table is read from a CSV dump (mysql -B -e 'select * from photlco' > photlco_old.csv).
Writes PNG figures and a JSON of summary numbers used by the report.
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.table import Table  # noqa: E402

FILT = {'B': 'B', 'V': 'V', 'gp': 'g', 'rp': 'r', 'ip': 'i'}
COLORS = {'B': '#4c72b0', 'V': '#55a868', 'g': '#64b5cd', 'r': '#c44e52', 'i': '#8172b2'}


def paper_table(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if 'LCO' not in line or '&' not in line or 'caption' in line:
            continue
        p = [c.strip() for c in line.split('&')]
        jd = 2460000 + float(p[1])
        for f, cell in zip('BgVri', p[3:8]):
            m = re.match(r'([\d.]+)\s*±\s*([\d.]+)', cell)
            if m:
                rows.append(dict(jd=jd, filter=f, mag=float(m.group(1)), dmag=float(m.group(2))))
    return Table(rows=rows)


def old_rows(csv):
    t = Table.read(csv, format='ascii.tab')
    return {r['filename']: dict(zip(t.colnames, r)) for r in t}


def new_rows(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return {r['filename']: dict(r) for r in c.execute('select * from photlco')
            if not any(t in r['filename'] for t in ('.zp.diff', '.cut.diff'))}  # option-test products


def paired(old, new, col, filetype=None):
    out = []
    for fn, o in old.items():
        n = new.get(fn)
        if n is None or (filetype and int(o['filetype']) != filetype):
            continue
        a, b = o.get(col), n.get(col)
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            continue
        out.append((fn, a, b, o['filter'], o['mjd']))
    return out


def scatter_panel(ax, pairs, label, lim=None, good=lambda a, b: a < 99 and b < 99):
    p = [x for x in pairs if good(x[1], x[2])]
    if not p:
        return {}
    a, b = np.array([x[1] for x in p]), np.array([x[2] for x in p])
    d = b - a
    for f in FILT:
        s = np.array([x[3] == f for x in p])
        if s.any():
            ax.scatter(a[s], d[s], s=10, color=COLORS[FILT[f]], label=FILT[f])
    ax.axhline(0, color='k', lw=0.5)
    ax.set_xlabel(f'old {label}')
    ax.set_ylabel(f'new − old {label}')
    if lim:
        ax.set_ylim(-lim, lim)
    ax.legend(fontsize=7, ncol=5)
    med, mad = float(np.median(d)), float(1.4826 * np.median(np.abs(d - np.median(d))))
    ax.set_title(f'{label}: median {med:+.4f}, robust σ {mad:.4f}, n={len(d)}')
    return dict(n=len(d), median=med, robust_sigma=mad, n_old_only=sum(1 for x in pairs if x[1] < 99 <= x[2]),
                n_new_only=sum(1 for x in pairs if x[2] < 99 <= x[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old-run', required=True)
    ap.add_argument('--old-csv', required=True)
    ap.add_argument('--new-run', required=True)
    ap.add_argument('--paper')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    old, new = old_rows(a.old_csv), new_rows(Path(a.new_run) / 'snpipe.sqlite')
    summary = {}

    # PSF stage: aperture correction and sn2 PSF magnitudes
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    summary['apercorr'] = scatter_panel(ax[0], paired(old, new, 'apercorr', 1), 'aperture correction', 0.06,
                                        good=lambda x, y: abs(x) < 1 and abs(y) < 1)
    ds = []
    for fn, o in old.items():
        if int(o['filetype']) != 1 or fn not in new:
            continue
        po, pn = Path(o['filepath']) / fn.replace('.fits', '.sn2.fits'), Path(new[fn]['filepath']) / fn.replace('.fits', '.sn2.fits')
        if po.exists() and pn.exists():
            od, nd = fits.getdata(po, 1), fits.getdata(pn, 1)
            if len(od) == len(nd):
                g = (od['smagf'] < 99) & (nd['smagf'] < 99) & (od['magp3'] < -6)
                if g.sum() > 10:
                    ds.append((o['filter'], float(np.median(nd['smagf'][g] - od['smagf'][g])),
                               float(1.4826 * np.median(np.abs(nd['smagf'][g] - od['smagf'][g] -
                                                               np.median(nd['smagf'][g] - od['smagf'][g]))))))
    if ds:
        for f in FILT:
            s = [x for x in ds if x[0] == f]
            if s:
                ax[1].scatter([x[1] for x in s], [x[2] for x in s], s=10, color=COLORS[FILT[f]], label=FILT[f])
        ax[1].set_xlabel('per-frame median (new − old) sn2 PSF mag of bright stars')
        ax[1].set_ylabel('per-frame robust σ')
        ax[1].legend(fontsize=7)
        summary['sn2_psf'] = dict(n_frames=len(ds), median_of_medians=float(np.median([x[1] for x in ds])),
                                  median_sigma=float(np.median([x[2] for x in ds])))
    fig.tight_layout()
    fig.savefig(out / 'psf_stage.png', dpi=110)
    plt.close(fig)

    # zero points and magnitudes
    for col, ft, name, lim in (('z1', 1, 'zero point z1 (unsubtracted)', 0.1), ('psfmag', 1, 'target psfmag (unsubtracted)', 0.2),
                               ('mag', 1, 'calibrated mag (unsubtracted)', 0.2), ('z1', 3, 'zero point z1 (difference)', 0.1),
                               ('apmag', 3, 'target apmag (difference)', 0.2), ('mag', 3, 'calibrated mag (difference)', 0.2)):
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        summary[f'{col}_ft{ft}'] = scatter_panel(ax, paired(old, new, col, ft), name, lim)
        fig.tight_layout()
        fig.savefig(out / f'{col}_ft{ft}.png', dpi=110)
        plt.close(fig)

    # light curves vs the paper
    if a.paper:
        pap = paper_table(a.paper)
        fig, ax = plt.subplots(2, 1, figsize=(10, 9), sharex=True, gridspec_kw=dict(height_ratios=[2, 1]))
        res = {}
        for label, rows, mk in (('old', old, 'o'), ('new', new, 's')):
            pts = [(float(r['mjd']) + 2400000.5, FILT[r['filter']], float(r['mag']), float(r['dmag']))
                   for r in rows.values() if int(r['filetype']) == 3 and r['filter'] in FILT and float(r['mag']) < 99]
            for f in 'BgVri':
                s = np.array([p for p in pts if p[1] == f], dtype=object)
                if not len(s):
                    continue
                jd, m = s[:, 0].astype(float), s[:, 2].astype(float)
                off = {'B': 1, 'g': 0.5, 'V': 0, 'r': -0.5, 'i': -1}[f]
                ax[0].plot(jd - 2460000, m + off, mk, ms=3, mfc='none' if label == 'old' else COLORS[f],
                           color=COLORS[f], label=f'{label} {f}{off:+g}' if f == 'B' or label == 'new' else None)
                pf = pap[pap['filter'] == f]
                # nearest paper point within 0.02 d
                d = []
                for j, mm in zip(jd, m):
                    k = np.argmin(np.abs(pf['jd'] - j))
                    if abs(pf['jd'][k] - j) < 0.02:
                        d.append((j, mm - pf['mag'][k]))
                if d:
                    d = np.array(d)
                    ax[1].plot(d[:, 0] - 2460000, d[:, 1], mk, ms=3, color=COLORS[f], mfc='none' if label == 'old' else COLORS[f])
                    res[f'{label}_{f}'] = dict(n=len(d), median=float(np.median(d[:, 1])),
                                               robust_sigma=float(1.4826 * np.median(np.abs(d[:, 1] - np.median(d[:, 1])))))
        for f in 'BgVri':
            pf = pap[pap['filter'] == f]
            off = {'B': 1, 'g': 0.5, 'V': 0, 'r': -0.5, 'i': -1}[f]
            ax[0].plot(pf['jd'] - 2460000, pf['mag'] + off, '-', color=COLORS[f], lw=0.8, alpha=0.6)
        ax[0].invert_yaxis()
        ax[0].set_ylabel('mag + offset')
        ax[0].legend(fontsize=7, ncol=3)
        ax[0].set_title('SN 2024pxl LCO difference-imaging light curve: lines = Singh et al. 2026, '
                        'open = old pipeline, filled = new')
        ax[1].axhline(0, color='k', lw=0.5)
        ax[1].set_ylim(-0.3, 0.3)
        ax[1].set_xlabel('JD − 2460000')
        ax[1].set_ylabel('pipeline − paper')
        fig.tight_layout()
        fig.savefig(out / 'lightcurve_vs_paper.png', dpi=110)
        plt.close(fig)
        summary['vs_paper'] = res
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
