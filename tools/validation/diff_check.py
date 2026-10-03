"""Check difference images independently of the pipeline that made them, and compare two reductions.

1. Field-star cancellation (snpipe.diff.field_star_residual, also a QA metric of the diff stage): the median
   fraction of field-star flux left in each difference image (0 = the stars cancel).
2. Optionally, the calibrated magnitudes of the transient in two reductions (e.g. LCO reference vs PS1 reference)
   on the same science frames, and each against the unsubtracted magnitude.

usage: python tools/validation/diff_check.py WORKDIR [--other WORKDIR2] [--class 1m0] [-o out.json]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from snpipe.diff import field_star_residual  # noqa: E402


def rows(workdir, filetype):
    c = sqlite3.connect(f'file:{Path(workdir) / "snpipe.sqlite"}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return {r['filename']: dict(r) for r in c.execute('SELECT * FROM photlco WHERE filetype=?', (filetype,))}


def default_diff(name):
    return '.diff.' in name and not any(t in name for t in ('.zp.', '.cut.', '.fit.'))


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument('workdir')
    a.add_argument('--other', help='second working directory to compare with (same science frames)')
    a.add_argument('--class', dest='cls', default='1m0', help='telescope class: 1m0, 0m4, 2m0 or all')
    a.add_argument('-o', '--output')
    args = a.parse_args(argv)
    out = {}
    for label, wd in (('a', args.workdir), ('b', args.other)):
        if not wd:
            continue
        sci, dif = rows(wd, 1), rows(wd, 3)
        res = {}
        for name, r in dif.items():
            if not default_diff(name) or (args.cls != 'all' and name[3:6] != args.cls):
                continue
            sname = name.split('.optimal')[0] + '.fits'
            item = dict(filter=r['filter'], mag=r['mag'] if r['mag'] and r['mag'] < 99 else None,
                        unsub=sci.get(sname, {}).get('mag'), science=sname)
            try:
                item['stars'] = field_star_residual(Path(r['filepath']) / name)
            except Exception as ex:
                item['stars'] = {'error': f'{type(ex).__name__}: {ex}'}
            res[sname] = item
        out[label] = {'workdir': wd, 'frames': res}
    summary = {}
    for label, d in out.items():
        fr = d['frames'].values()
        resid = np.array([f['stars']['residual'] for f in fr if f['stars'] and 'residual' in f['stars']])
        du = np.array([f['mag'] - f['unsub'] for f in fr if f['mag'] and f['unsub'] and f['unsub'] < 99])
        summary[label] = dict(n_diff=len(d['frames']), n_star_check=int(len(resid)),
                              star_residual_median=float(np.median(resid)) if len(resid) else None,
                              star_residual_abs_gt_2pct=int(np.sum(np.abs(resid) > 0.02)),
                              diff_minus_unsub_median=float(np.median(du)) if len(du) else None,
                              diff_brighter_than_unsub_by_0p05=int(np.sum(du < -0.05)))
    if 'b' in out:
        common = set(out['a']['frames']) & set(out['b']['frames'])
        dm = {}
        for s in common:
            fa, fb = out['a']['frames'][s], out['b']['frames'][s]
            if fa['mag'] and fb['mag']:
                dm.setdefault(fa['filter'], []).append(fb['mag'] - fa['mag'])
        summary['b_minus_a_by_filter'] = {f: dict(n=len(v), median=float(np.median(v)),
                                                  robust_sigma=float(1.4826 * np.median(np.abs(np.array(v) - np.median(v)))))
                                          for f, v in sorted(dm.items())}
    out['summary'] = summary
    print(json.dumps(summary, indent=1))
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    main()
