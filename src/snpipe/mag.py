"""Stage ``mag``: apparent magnitudes of the target from instrumental mags, zero points and colour terms.

Port of ``calibratemag.py -s mag`` (the arithmetic is unchanged and uses numpy.ma like the original):
* instrumental mag = psfmag (``--type fit``) or apmag (``--type ph``, default for difference images),
  airmass-corrected with the site extinction coefficients;
* for each night/telescope/instrument group and each colour of ``chosecolor(usegood=True)``, the colour
  of the target is solved from the two bands' flux-averaged mags, zero points and colour terms:
  colour = (m0 - m1 + z0 - z1) / (1 - c0 + c1);
* mag = inst + Z + C * colour (no colour correction when the other band is missing), dmag propagated.
Groups use the telescope and instrument names (the old code used their MySQL ids; one-to-one) and the
site code (``telescopes.shortname`` = SITEID).
"""
import numpy.ma as np
from numpy import pi  # noqa: F401
from astropy.table import Table

from astropy.io import fits

from . import db, sites
from .headers import readkey
from .qa import FrameQA


def average_in_flux(mag, dmag, axis=None):
    flux = 10 ** (mag / -2.5)
    dflux = np.log(10) / 2.5 * flux * dmag
    avg_dflux = np.power(np.sum(np.power(dflux, -2), axis), -0.5)
    avg_flux = np.sum(flux * np.power(dflux, -2), axis) * avg_dflux ** 2
    return -2.5 * np.log10(avg_flux), 2.5 / np.log(10) * np.divide(avg_dflux, avg_flux)


def image_table(frames, magcol, errcol, conn=None):
    rows = [db.get_frame(f, conn) for f in frames]
    cols = ['filter', 'filepath', 'filename', 'airmass', 'dayobs', 'targetid', 'telescope', 'instrument',
            'zcol1', 'z1', 'c1', 'dz1', 'dc1', 'zcol2', 'z2', 'c2', 'dz2', 'dc2', magcol, errcol]
    t = Table({c: [r[c] for r in rows] for c in cols}, masked=True)
    t['shortname'] = [r['filename'][:3] for r in rows]
    # extinction must use the airmass and site of the image whose stars gave the zero point (the sn2 header
    # zcat read). For a difference image normalized to the template (PHOTNORM=t) that is the template, not
    # the science frame whose row the diff copied (old pipeline bug: error k_t*X_t - k_s*X_s, up to 0.15 mag).
    ext_site, ext_airmass, ext_ok = [], [], []
    for r in rows:
        site, am, ok = r['filename'][:3], r['airmass'], True
        sn2 = str(r['filepath']) + '/' + r['filename'].replace('.fits', '.sn2.fits')
        try:
            h = fits.getheader(sn2)
            site, am = h['SITEID'], float(readkey(h, 'airmass'))
        except (OSError, KeyError, TypeError, ValueError):
            # a science frame's own row has the same values; a difference image does not (its zero point belongs
            # to the image it is normalised to): without that header its magnitude cannot be calibrated
            ok = '.diff.' not in r['filename']
        ext_site.append(site if site in sites.extinction else r['filename'][:3])
        ext_airmass.append(am)
        ext_ok.append(ok)
    t['ext_site'], t['ext_airmass'], t['ext_ok'] = ext_site, ext_airmass, ext_ok
    t[magcol].mask |= ~np.asarray(ext_ok)
    t['filter'] = [sites.filterst1[f] for f in t['filter']]
    t.rename_column(magcol, 'instmag')
    t.rename_column(errcol, 'dinstmag')
    for c in t.colnames:
        if t[c].dtype.kind == 'f':
            t[c].mask |= t[c] >= 9999.
        if t[c].dtype.kind == 'O':
            t[c] = ['' if v is None else v for v in t[c]]
    return t


def run(frames, typemag='fit', match_by_site=False, conn=None):
    magcol, errcol = ('psfmag', 'psfdmag') if typemag == 'fit' else ('apmag', 'dapmag')
    t = image_table(frames, magcol, errcol, conn)
    color_to_use = sites.chosecolor(t['filter'], True)
    colors_to_calculate = set(sum(color_to_use.values(), []))
    tel_kwd, inst_kwd = ('shortname', 'instrument') if match_by_site else ('telescope', 'instrument')
    extinction = [sites.extinction[r['ext_site']][r['filter']] for r in t]
    t['instmag_amcorr'] = (t['instmag'].T - extinction * t['ext_airmass']).T
    t = t.group_by(['dayobs', tel_kwd, inst_kwd])
    for filters in colors_to_calculate:
        colors, dcolors = [], []
        for group in t.groups:
            f0, f1 = group['filter'] == filters[0], group['filter'] == filters[1]
            m0, dm0 = average_in_flux(group['instmag_amcorr'][f0], group['dinstmag'][f0], axis=0)
            m1, dm1 = average_in_flux(group['instmag_amcorr'][f1], group['dinstmag'][f1], axis=0)
            z0, dz0 = average_in_flux(group['z1'][f0], group['dz1'][f0])
            z1, dz1 = average_in_flux(group['z2'][f1], group['dz2'][f1])
            if np.all(group['dc1'][f0]):
                dc0 = np.sum(np.power(group['dc1'][f0], -2)) ** -0.5
                c0 = np.sum(group['c1'][f0] * np.power(group['dc1'][f0], -2)) * dc0 ** 2
            else:
                dc0, c0 = 0., np.mean(group['c1'][f0])
            if np.all(group['dc2'][f1]):
                dc1 = np.sum(np.power(group['dc2'][f1], -2)) ** -0.5
                c1 = np.sum(group['c2'][f1] * np.power(group['dc2'][f1], -2)) * dc1 ** 2
            else:
                dc1, c1 = 0., np.mean(group['c2'][f1])
            color = np.divide(m0 - m1 + z0 - z1, 1 - c0 + c1)
            dcolor = np.abs(color) * np.sqrt(np.divide(dm0 ** 2 + dm1 ** 2 + dz0 ** 2 + dz1 ** 2, (m0 - m1 + z0 - z1) ** 2)
                                             + np.divide(dc0 ** 2 + dc1 ** 2, (1 - c0 + c1) ** 2))
            for _ in group:
                colors.append(color)
                dcolors.append(dcolor)
        t[filters] = np.array(colors)
        t['d' + filters] = np.array(dcolors)
    zcol = [color_to_use[r['filter']][0] if color_to_use[r['filter']] else r['filter'] * 2 for r in t]
    sel = np.array(zcol) == t['zcol1']
    zp = np.choose(sel, [t['z2'], t['z1']])
    dzp = np.choose(sel, [t['dz2'], t['dz1']])
    ct = np.choose(sel, [t['c2'], t['c1']])
    dct = np.choose(sel, [t['dc2'], t['dc1']])
    uz, iz = np.unique(zcol, return_inverse=True)
    col_used = np.choose(iz, [t[c].T if c in t.colnames else 0. for c in uz]).filled(0.)
    dcol_used = np.choose(iz, [t['d' + c].T if c in t.colnames else 0. for c in uz]).filled(0.)
    t['mag'] = (t['instmag_amcorr'].T + zp + ct * col_used).T
    t['dmag'] = np.sqrt(t['dinstmag'].T ** 2 + dzp ** 2 + dct ** 2 * col_used ** 2 + ct ** 2 * dcol_used ** 2).T
    t['dmag'].mask = t['mag'].mask
    out = t.filled(9999.)
    qas = []
    for r, raw in zip(out, t):
        db.update(r['filename'], conn, mag=float(r['mag']), dmag=float(r['dmag']))
        q = FrameQA(r['filename'], 'mag', metrics=dict(mag=float(r['mag']), dmag=float(r['dmag']),
                                                       filter=r['filter'], zcol=zcol[len(qas)], typemag=typemag))
        if not r['ext_ok']:
            q.fail('star table (sn2) of the difference image missing or unreadable: airmass/site of its zero-point '
                   'image unknown (rerun diff)')
        elif r['mag'] >= 9999:
            q.fail('no magnitude (missing zero point, colour or instrumental mag)')
        elif '.diff.' in r['filename']:
            # physical gate: the transient's flux in the difference cannot exceed the total light (transient + host)
            # in an aperture on the unsubtracted frame. That total is the unsubtracted calibrated magnitude moved from
            # its PSF to its aperture magnitude (same zero point and colour); the PSF magnitude itself is no bound
            # (on a bright host or a faded transient the PSF fit can fail, e.g. 2025rbs at +400 d: PSF-ap +4 mag)
            pair = db.query('SELECT namein FROM photpairing WHERE nameout=?', (r['filename'],), conn)
            src = db.get_frame(pair[0]['namein'], conn) if pair else None
            if (src and src['mag'] is not None and src['mag'] < 99 and src['apmag'] is not None and src['apmag'] < 99
                    and src['psfmag'] is not None and src['psfmag'] < 99):
                total = float(src['mag'] + src['apmag'] - src['psfmag'])
                q.metrics.update(mag_unsubtracted=float(src['mag']), mag_unsubtracted_aperture=total)
                q.check('diff_minus_unsubtracted_aperture', float(r['mag'] - total), lo=-0.2)
        qas.append(q)
    return qas
