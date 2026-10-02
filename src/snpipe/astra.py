"""Write an ASTRA record (``astra.yaml`` + ``universes/baseline.yaml``) for one target's reduction.

Every stage is an ASTRA Output whose recipe is the real ``snpipe`` command; the stage's QA summary
(``qa/<stage>-latest.json``: status, per-frame metrics, thresholds) is the materialised output, so an
agent executing the record can gate each step on it and on the command's exit code
(0 ok, 1 QA fail, 2 config, 3 missing input, 4 external service). Every consequential choice that the
old pipeline made through command-line defaults is an explicit Decision.
"""
from pathlib import Path

import yaml


def _qa(stage):
    return f'cp qa/{stage}-latest.json {{output}}'


def spec_version():
    """Version of the installed astra-spec (the record declares the schema it was validated against)."""
    try:
        from importlib.metadata import version
        return version('astra-spec')
    except Exception:
        return '0.0.14'


def build(target, ra, dec, epoch, tempdate, raw_dir, template_dir, aliases=()):
    e = f'-n {target} -e {epoch}'
    t = f'-n {target} -e {tempdate}'
    out = []

    def o(id_, typ, fmt, desc, inputs, cmd, decisions=()):
        d = dict(id=id_, type=typ, format=fmt, description=desc, inputs=list(inputs))
        if decisions:
            d['decisions'] = list(decisions)
        d['recipe'] = dict(command=cmd)
        out.append(d)

    alias = ' '.join(aliases)
    o('target_registered', 'metric', 'json', 'Target in the pipeline database (SNEx-equivalent coordinates)',
      ['raw_frames'], f'snpipe add-target {target} --ra {ra} --dec {dec} --alias {alias} > {{output}}')
    o('ingest_qa', 'metric', 'json', 'Science frames placed and registered (funpack-equivalent unpacking)',
      ['raw_frames', 'target_registered'],
      f'snpipe ingest --target {target} --frames-json {{inputs.raw_frames}}/frames.json '
      f'--local-dir {{inputs.raw_frames}} > {{output}}')
    o('template_ingest_qa', 'metric', 'json', 'Pre-explosion reference frames placed and registered',
      ['template_frames', 'target_registered'],
      f'snpipe ingest --target {target} --frames-json {{inputs.template_frames}}/frames.json '
      f'--local-dir {{inputs.template_frames}} > {{output}}')
    o('catalogs', 'metric', 'json', 'APASS / SDSS (or PS1) / Gaia field catalogs, old cuts and formats',
      ['target_registered'], f'snpipe catalogs --target {target} --sloan-source {{decisions.sloan_source}} > {{output}}',
      ['sloan_source'])
    for name, sel, ins in (('cosmic_qa', e, ['ingest_qa']), ('template_cosmic_qa', t, ['template_ingest_qa'])):
        o(name, 'metric', 'json', 'L.A.Cosmic (astroscrappy, sigclip 4.5, sigfrac 0.2, objlim 4) per frame',
          ins, f'snpipe cosmic {sel} -j 8 && {_qa("cosmic")}')
    psf_dec = ['psf_model', 'psf_auto_fix', 'max_apercorr', 'psf_nstars']
    psf_cmd = ('--model {decisions.psf_model} --auto-fix {decisions.psf_auto_fix} '
               '--max-apercorr {decisions.max_apercorr} --nstars {decisions.psf_nstars}')
    o('psf_qa', 'metric', 'json', 'PSF model, aperture correction (gate |apco|<=max) and sn2 table per frame',
      ['cosmic_qa', 'catalogs'], f'snpipe psf {e} -j 8 {psf_cmd} && {_qa("psf")}', psf_dec)
    o('psfmag_qa', 'metric', 'json', 'Target PSF + aperture photometry on unsubtracted frames',
      ['psf_qa'], f'snpipe psfmag {e} -j 8 && {_qa("psfmag")}')
    zc = 'snpipe zcat {sel} -f landolt --field {{decisions.bv_catalog}} && snpipe zcat {sel} -f sloan --field {{decisions.gri_catalog}}'
    o('zcat_qa', 'metric', 'json', 'Zero points and colour terms (fixed colour terms, 2-sigma clipping)',
      ['psf_qa'], zc.format(sel=e) + f' && {_qa("zcat")}', ['bv_catalog', 'gri_catalog'])
    o('mag_qa', 'metric', 'json', 'Calibrated target magnitudes (unsubtracted, PSF)', ['psfmag_qa', 'zcat_qa'],
      f'snpipe mag {e} --type fit && cp qa/mag-latest.json {{output}}')
    o('template_qa', 'metric', 'json', 'Reference frames marked (filetype 4), cleaned and PSF-modelled',
      ['template_cosmic_qa', 'catalogs'],
      f'snpipe template {t} && snpipe cosmic {t} --filetype 4 -j 8 && '
      f'snpipe psf {t} --filetype 4 -j 8 {psf_cmd} && {_qa("psf")}', psf_dec)
    o('diff_qa', 'metric', 'json', 'PyZOGY difference images (template = earliest reference per filter)',
      ['psf_qa', 'template_qa'],
      f'snpipe diff {e} -j 4 --tempdate {tempdate} --temptel {{decisions.template_camera}} '
      f'--normalize {{decisions.diff_normalize}} --register {{decisions.diff_register}} '
      f'--region {{decisions.diff_region}} && {_qa("diff")}',
      ['template_camera', 'diff_normalize', 'diff_register', 'diff_region'])
    o('diff_phot_qa', 'metric', 'json', 'PSF of the difference images, target photometry on them',
      ['diff_qa'], f'snpipe psf {e} --filetype 3 -j 8 && snpipe psfmag {e} --filetype 3 -j 8 && {_qa("psfmag")}')
    o('diff_zcat_qa', 'metric', 'json', 'Zero points of the difference images (from the reference sn2)',
      ['diff_phot_qa'], zc.format(sel=e + ' --filetype 3') + ' --type {decisions.diff_phot_type}' +
      f' && {_qa("zcat")}', ['bv_catalog', 'gri_catalog', 'diff_phot_type'])
    o('light_curve', 'table', 'csv', 'Template-subtracted calibrated light curve (dateobs, jd, mag, dmag, '
      'telescope, filter, magtype)', ['diff_zcat_qa'],
      f'snpipe mag {e} --filetype 3 --type {{decisions.diff_phot_type}} && '
      f'snpipe getmag {e} --filetype 3 --type mag -o {{output}}', ['diff_phot_type'])
    o('review_queue', 'report', 'json', 'Frames for agent/human review: all warn/fail + a random ok sample, '
      'with PNG packets (replaces the interactive check* stages)', ['psf_qa', 'psfmag_qa', 'diff_qa'],
      'snpipe review psf --ensemble apco fwhm_psf_x_pix && snpipe review psfmag && snpipe review diff && '
      'cat review/*/queue.json > {output}')

    decisions = {
        'sloan_source': dict(
            label='Catalog for the SDSS-filter calibration',
            rationale='Changes every gri zero point; the old pipeline uses SDSS unless the field is not covered.',
            default='sdss', options={'sdss': {'label': 'SDSS DR PhotoPrimary (comparecatalogs default)'},
                                     'panstarrs': {'label': 'Pan-STARRS1 DR1 (comparecatalogs -p)'}}),
        'bv_catalog': dict(
            label='Catalog for B,V zero points', default='apass',
            rationale='B and V cannot be calibrated to SDSS; APASS is the field catalog the manual uses.',
            options={'apass': {'label': 'APASS DR9'}, 'landolt': {'label': 'Local Landolt sequence (needs standards)'}}),
        'gri_catalog': dict(label='Catalog for g,r,i zero points', default='sloan',
                            rationale='Singh et al. calibrate gri to SDSS.',
                            options={'sloan': {'label': 'SDSS (or PS1 file)'}, 'apass': {'label': 'APASS'}}),
        'psf_model': dict(
            label='PSF model', default='daophot',
            rationale='The PSF shape enters every PSF magnitude and the aperture correction.',
            options={'daophot': {'label': 'Pixel-integrated Gaussian + 2x residual lookup table (DAOPHOT recipe)'},
                     'epsf': {'label': 'photutils EPSFBuilder empirical PSF'}}),
        'psf_auto_fix': dict(
            label='Remediation ladder for failed PSFs', default='ladder',
            rationale='The manual tells the user to retry a failed PSF with larger FWHM, lower datamax, '
                      'more stars or another catalog; without it those frames are lost.',
            options={'ladder': {'label': "Apply the manual's fixes automatically"},
                     'off': {'label': 'Single attempt, as an unattended old run'}}),
        'psf_nstars': dict(
            label='Number of PSF stars', default='n6',
            rationale='Old default 6 (lscpsf -p 6). With a constant PSF over the frame, 6 stars leave a '
                      '0.02-0.04 mag bias and 0.07-0.10 mag scatter of PSF vs aperture mags on 1-m frames '
                      '(both pipelines); the manual suggests 12 as a remedy.',
            options={'n6': {'label': '6 (old default)'}, 'n12': {'label': '12'}, 'n20': {'label': '20'}}),
        'max_apercorr': dict(label='Aperture-correction gate (mag)', default='apco_0p1',
                             rationale='Old pipeline default --max_apercorr 0.1.',
                             options={'apco_0p1': {'label': '0.1 mag'}, 'apco_0p2': {'label': '0.2 mag (looser)'}}),
        'template_camera': dict(label='Camera of the reference frames', default='fl',
                                rationale='The 2018-03-07 references were taken with the 1-m Sinistro fl05.',
                                options={'fl': {'label': '1-m Sinistro (fl)'}}),
        'diff_normalize': dict(label='Photometric normalisation of the difference', default='t',
                               rationale='lscloop default --normalize t: differences in reference units, '
                                         'calibrated with the reference field stars.',
                               options={'t': {'label': 'reference (template)'}, 'i': {'label': 'science image'}}),
        'diff_register': dict(label='Resampling of the reference onto the science grid', default='adaptive',
                              rationale='The old default was IRAF gregister drizzle (flux conserving); the '
                                        'manual warns the --no_iraf bilinear path may be worse.',
                              options={'adaptive': {'label': 'reproject_adaptive, flux conserving (closest to drizzle)'},
                                       'exact': {'label': 'reproject_exact (area overlap) x pixel-area ratio; slow'},
                                       'bilinear': {'label': 'reproject_interp bilinear x pixel-area ratio'}}),
        'diff_region': dict(label='Area of the frame that is subtracted', default='full',
                            rationale='The old pipeline subtracts the full frame (PyZOGY: ~6.9 GB and ~3 min per 4k '
                                      'frame). A 2048x2048 cutout around the target is ~4x cheaper; the gain fit then '
                                      'uses only the stars of that region.',
                            options={'full': {'label': 'full frame (old pipeline)'},
                                     'cutout': {'label': '2048x2048 px around the target'}}),
        'diff_phot_type': dict(label='Photometry on difference images', default='ph',
                               rationale='lscloop uses aperture photometry for difference images by default '
                                         '(the PyZOGY PSF is neither the science nor the reference PSF).',
                               options={'ph': {'label': 'aperture (3 FWHM)'}, 'fit': {'label': 'PSF fit'}}),
    }
    tid = target.lower() if target[0].isalpha() else 'sn' + target.lower()
    rec = dict(version=spec_version(), id=f'{tid}_lco_photometry', name=f'{target} LCO photometry (snpipe)',
               description=(f'IRAF-free reduction of LCO BANZAI frames of {target} with snpipe (lcogtsnpipe-ai): '
                            'ingest, catalogs, cosmic rays, PSF, PSF/aperture photometry, zero points, PyZOGY '
                            'difference imaging and calibration, with per-stage QA gates and review packets.'),
               tags=['photometry', 'lco', 'supernova', 'difference-imaging'],
               inputs=[dict(id='raw_frames', type='data', source=str(raw_dir),
                            description='BANZAI e91 frames (+ frames.json from the archive query)'),
                       dict(id='template_frames', type='data', source=str(template_dir),
                            description='Pre-explosion reference frames (+ frames.json)')],
               outputs=out, decisions=decisions)
    universe = dict(id='baseline', description='Old-pipeline defaults (Singh et al. setup: SDSS gri, PyZOGY)',
                    decisions={k: v['default'] for k, v in decisions.items()})
    return rec, universe


def write(path, *args, **kw):
    rec, uni = build(*args, **kw)
    path = Path(path)
    (path / 'universes').mkdir(parents=True, exist_ok=True)
    (path / 'astra.yaml').write_text(yaml.safe_dump(rec, sort_keys=False, width=110))
    (path / 'universes' / 'baseline.yaml').write_text(yaml.safe_dump(uni, sort_keys=False))
    return path / 'astra.yaml'
