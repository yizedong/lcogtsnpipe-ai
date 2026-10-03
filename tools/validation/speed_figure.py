"""Speed of the old and the new pipeline, stage by stage, from the controlled benchmark.

Both pipelines reduced the same SN 2024pxl frames (100 science + 18 reference) one after the other on the same
kind of node (Intel Xeon Platinum 8268, 8 cores, 16 GB, node-local disk); timings exclude data staging.
Input: docs/validation/sn2024pxl/benchmark/timing_{old,new}.json. Output: .../visual/speed_by_stage.png and .pdf.

usage: python tools/validation/speed_figure.py
"""
import json
from pathlib import Path

import matplotlib
import matplotlib.ticker
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / 'docs' / 'validation' / 'sn2024pxl' / 'benchmark'
OUT = ROOT / 'docs' / 'validation' / 'sn2024pxl' / 'visual' / 'speed_by_stage'

# rows: (label, old stage names, new stage names)
ROWS = [
    ('Subtraction (PyZOGY)', ['diff (1m, fa)', 'diff (0.4m, sq)'], ['diff']),
    ('PSF model, science frames', ['psf'], ['psf']),
    ('PSF model, reference frames', ['psf (templates)', 'psf (templates ft4)'], ['psf (templates ft4)']),
    ('Transient photometry', ['psfmag'], ['psfmag']),
    ('Photometry on differences', ['psf (diff)', 'psfmag (diff)'], ['psf (diff)', 'psfmag (diff)']),
    ('Cosmic rays', ['cosmic', 'cosmic (templates)', 'cosmic (templates ft4)'],
     ['cosmic', 'cosmic (templates)', 'cosmic (templates ft4)']),
    ('Ingest', ['ingest (science)', 'ingest (templates)'], ['ingest (science)', 'ingest (templates)']),
    ('Zero points', ['zcat apass', 'zcat sloan', 'zcat apass (diff)', 'zcat sloan (diff)'],
     ['zcat apass', 'zcat sloan', 'zcat apass (diff)', 'zcat sloan (diff)']),
    ('Reference marking', ['template'], ['template']),
    ('Calibration + light curves', ['mag', 'mag (diff)', 'getmag (diff)', 'getmag (unsubtracted)'],
     ['mag', 'mag (diff)', 'getmag (diff)', 'getmag (unsubtracted)']),
]
OLD_C, NEW_C = '#eb6834', '#2a78d6'           # categorical slots 2 and 1 of the reference palette
INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'


def stage_seconds(path):
    d = json.loads(path.read_text())
    return {s['stage']: s['seconds'] for s in d['stages']}, d


def main():
    old, od = stage_seconds(BENCH / 'timing_old.json')
    new, nd = stage_seconds(BENCH / 'timing_new.json')
    rows = [(lab, sum(old[s] for s in o), sum(new[s] for s in n)) for lab, o, n in ROWS]
    rows.sort(key=lambda r: r[1])
    total_old, total_new = od['total_stage_seconds'], nd['total_stage_seconds']
    labels = [r[0] for r in rows] + ['All stages']
    told = [r[1] for r in rows] + [total_old]
    tnew = [r[2] for r in rows] + [total_new]

    fig, ax = plt.subplots(figsize=(8.6, 5.6), facecolor=SURF)
    ax.set_facecolor(SURF)
    y = list(range(len(labels)))
    y[-1] += 0.6                               # the total, set apart
    for yi, a, b in zip(y, told, tnew):
        ax.plot([b, a], [yi, yi], color=GRID, lw=2.5, zorder=1, solid_capstyle='round')
    ax.scatter(told, y, s=110, marker='s', color=OLD_C, edgecolor=SURF, linewidth=2, zorder=2,
               label='old pipeline (lcogtsnpipe, IRAF)')
    ax.scatter(tnew, y, s=80, marker='o', color=NEW_C, edgecolor=SURF, linewidth=2, zorder=3,
               label='new pipeline (snpipe)')
    ax.set_xscale('log')
    xmax = max(told) * 9
    for yi, a, b, lab in zip(y, told, tnew, labels):
        f = a / b
        txt = f'{f:.1f}x faster' if f >= 1.05 else (f'{1 / f:.1f}x slower' if f < 0.95 else 'same')
        bold = lab == 'All stages'
        ax.text(xmax * 0.92, yi, txt, ha='right', va='center', fontsize=10 if bold else 9,
                color=INK if bold else INK2, fontweight='bold' if bold else 'normal')
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.5, color=INK)
    ax.get_yticklabels()[-1].set_fontweight('bold')
    ax.set_xlim(3, xmax)
    ticks = [(10, '10 s'), (60, '1 min'), (600, '10 min'), (3600, '1 h'), (4 * 3600, '4 h')]
    ax.set_xticks([t for t, _ in ticks])
    ax.set_xticklabels([lab for _, lab in ticks])
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlabel('time for 100 science + 18 reference frames (log scale)', color=INK2, fontsize=9)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8.5, length=0)
    h = total_old / 3600, total_new / 3600
    ax.set_title(f'SN 2024pxl, same frames and same hardware: {h[0]:.1f} h \u2192 {h[1]:.1f} h',
                 loc='left', fontsize=12, color=INK, pad=24)
    ax.text(0, 1.015, 'Intel Xeon 8268, 8 cores, 16 GB, node-local disk; subtraction limited to 2 parallel frames by '
                      'memory (16 GB)', transform=ax.transAxes, fontsize=8, color=INK2)
    ax.legend(loc='upper left', bbox_to_anchor=(0.0, 0.97), frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(f'{OUT}.{ext}', dpi=160, facecolor=SURF)
    print('wrote', OUT.with_suffix('.png'))
    for lab, a, b in zip(labels, told, tnew):
        print(f'{lab:30s} {a:8.0f} s {b:8.0f} s  x{a / b:.1f}')


if __name__ == '__main__':
    main()
