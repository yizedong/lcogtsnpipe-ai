"""Stage ``getmag``: light-curve table of the target (``myloopdef.run_getmag``).

Columns as the old output: dateobs, jd (= mjd + 2400000.5), mag, dmag, telescope, filter (short name),
magtype; rows with |mag| <= 99, sorted by jd. ``--type mag`` (calibrated), ``fit`` (psfmag) or ``ph``
(apmag with its own error ``dapmag``: the old code paired apmag with psfdmag — survey B bug 9, fixed).
Optional ``combine`` days: inverse-variance mean of points closer than that (same rule as the old code).
Written as real CSV (the old ``--output x.csv`` wrote a space-separated table) plus an ECSV with the
frame name of every point, so a reviewer can trace each point back to its packet.
"""
import numpy as np
from astropy.table import Table

from . import db, sites

COLS = {'mag': ('mag', 'dmag'), 'fit': ('psfmag', 'psfdmag'), 'ph': ('apmag', 'dapmag')}


def run(frames, mtype='mag', combine=1e-10, output=None, conn=None):
    mcol, ecol = COLS[mtype]
    rows = [db.get_frame(f, conn) for f in frames]
    rows = [r for r in rows if r[mcol] is not None and abs(r[mcol]) <= 99]
    t = Table({'dateobs': [str(r['dateobs']) for r in rows],
               'jd': np.array([r['mjd'] + 2400000.5 for r in rows]),
               'mag': np.array([r[mcol] for r in rows], float), 'dmag': np.array([r[ecol] for r in rows], float),
               'telescope': [r['telescope'] for r in rows], 'filter': [sites.filterst1[r['filter']] for r in rows],
               'magtype': [r['magtype'] for r in rows], 'filename': [r['filename'] for r in rows]})
    if combine > 1e-10 and len(t):
        out = []
        for g in t.group_by(['telescope', 'filter']).groups:
            g.sort('jd')
            i = 0
            while i < len(g):
                j = i + 1
                while j < len(g) and 0 <= g['jd'][j] - g['jd'][i] < combine:
                    j += 1
                s = g[i:j]
                if len(s) == 1:
                    out.append(dict(zip(s.colnames, s[0])))
                else:
                    w = 1 / s['dmag'] ** 2
                    m = np.sum(w * s['mag']) / np.sum(w)
                    d = np.sqrt(np.sum(w * (s['mag'] - m) ** 2) / np.sum(w)) + 0.01
                    out.append(dict(dateobs=s['dateobs'][len(s) // 2], jd=np.mean(s['jd']), mag=m, dmag=d,
                                    telescope=s['telescope'][0], filter=s['filter'][0],
                                    magtype=float(np.std(s['magtype'])), filename=','.join(s['filename'])))
                i = j
        t = Table(rows=out, names=t.colnames)
    t.sort('jd')
    t['jd'].format, t['mag'].format, t['dmag'].format = '%.5f', '%.4f', '%.4f'
    if output:
        t.write(output, format='csv', overwrite=True)
        t.write(str(output).rsplit('.', 1)[0] + '.ecsv', format='ascii.ecsv', overwrite=True)
    return t
