"""Build the static report website docs/index.html from docs/report/summary.json (+ figures).

usage: python tools/make_site.py   (run after tools/compare.py; serve docs/ with GitHub Pages)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / 'docs' / 'report'
S = json.loads((REP / 'summary.json').read_text())
EXTRA = json.loads((REP / 'extra.json').read_text()) if (REP / 'extra.json').exists() else {}


def f(v, d=3, sign=True):
    return ('{:+.%df}' % d if sign else '{:.%df}' % d).format(v) if isinstance(v, (int, float)) else '—'


def ms(key):
    s = S.get(key, {})
    return f"{f(s.get('median'))} ± {f(s.get('robust_sigma'), sign=False)} <span class=n>(n={s.get('n', '—')})</span>"


paper = S.get('vs_paper', {})
lc_rows = ''.join(
    f"<tr><td>{b}</td><td>{f(paper.get('old_' + b, {}).get('median'))} ± {f(paper.get('old_' + b, {}).get('robust_sigma'), sign=False)}"
    f" <span class=n>(n={paper.get('old_' + b, {}).get('n', '—')})</span></td>"
    f"<td>{f(paper.get('new_' + b, {}).get('median'))} ± {f(paper.get('new_' + b, {}).get('robust_sigma'), sign=False)}"
    f" <span class=n>(n={paper.get('new_' + b, {}).get('n', '—')})</span></td></tr>" for b in 'BgVri')

stages = [
    ('ingest + funpack', 'LCOGTingest + cfitsio funpack', 'astropy unpacking, threaded download', 'pixels identical in all extensions', 'I/O bound'),
    ('catalogs', 'comparecatalogs (vizquery, astroquery)', 'same queries, cuts, file formats', 'identical files', '—'),
    ('cosmic', 'astroscrappy', 'identical call', '<b>bit-identical</b> masks and clean images (18/18)', 'same algorithm'),
    ('wcs', 'trust BANZAI; human <code>checkwcs</code>', 'measured vs Gaia for every frame, refit if bad', 'new check', '≈1 s/frame'),
    ('psf — aperture photometry', 'daophot <code>phot</code>', 'photutils + IRAF centroid and sky rules', '<b>identical</b> (0.000 median and MAD)', ''),
    ('psf — model, PSF photometry', 'daophot psf (gauss+LUT), group, nstar', 'GaussianPRF + 2× LUT (DAOPHOT recipe) in ImagePSF; DAOPHOT grouping; PSFPhotometry with fitted sky',
     f"aperture correction {ms('apercorr')}; sn2 PSF mags {f(S.get('sn2_psf', {}).get('median_of_medians'))}, per-frame σ {f(S.get('sn2_psf', {}).get('median_sigma'), sign=False)}", '39–80 s → ≈15 s per frame; parallel'),
    ('psfmag', 'lscsn + daophot allstar', 'Legendre background, IRAF mode sky, PSFPhotometry', f"SN psfmag {ms('psfmag_ft1')}", '20 → 4.3 s/frame'),
    ('zcat', 'Python', 'ported line by line', f"z1 {ms('z1_ft1')}", ''),
    ('mag (unsubtracted)', 'calibratemag', 'ported', ms('mag_ft1'), ''),
    ('diff (PyZOGY)', 'geomap + gregister, seepsf, PyZOGY', 'flux-conserving reproject, seepsf-equivalent, PyZOGY with exact 60× faster bad-pixel fill', f"SN aperture mag {ms('apmag_ft3')}", '181 → 102 s/frame; 2 parallel'),
    ('zcat / mag on differences', 'Python', 'ported', f"z1 {ms('z1_ft3')}; <b>calibrated mag {ms('mag_ft3')}</b>", ''),
]
stage_rows = ''.join(f'<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td></tr>' for a, b, c, d, e in stages)
figs = [('visual/speed.png', 'Time to reduce the same 99 frames: old pipeline vs snpipe (hatched: estimated from per-frame times)'),
        ('visual/lightcurves_by_band_subset.png', 'Per band, subset epochs: Singh et al. (grey), old (open), new (filled), and residuals vs the paper'),
        ('visual/lightcurves_by_band.png', 'Per band, whole light curve'),
        ('visual/difference_images.png', 'Difference images around the SN: science, old, new, (new − old)/σ'),
        ('visual/sn_psf_fit_stamps.png', 'SN PSF-fit stamps of both pipelines (original and residual)'),
        ('visual/psf_models.png', 'PSF models: IRAF seepsf of the old PSF vs the new model, difference and radial profiles'),
        ('visual/one_to_one.png', 'New vs old, with residual panels'),
        ('visual/pulls.png', '(new − old) / combined error'),
        ('visual/timing.png', 'Seconds per frame, old vs new'),
        ('lightcurve_vs_paper.png', 'Difference-imaging light curve: Singh et al. (2026), old and new pipelines'),
        ('mag_ft3.png', 'Calibrated SN magnitudes on difference images, new − old'),
        ('apmag_ft3.png', 'SN aperture magnitudes on difference images, new − old'),
        ('psf_stage.png', 'PSF stage: aperture correction and sn2 PSF magnitudes, new − old'),
        ('psfmag_ft1.png', 'SN PSF magnitudes on unsubtracted frames, new − old'),
        ('z1_ft1.png', 'Zero points, new − old')]
fig_html = ''.join(f'<figure><img src="report/{p}" alt="{c}" loading=lazy><figcaption>{c}</figcaption></figure>'
                   for p, c in figs if (REP / p).exists())
packets = [('packets/psf_companion_0087.png', 'PSF star 1 has a companion 10 px S — its light becomes a ghost in the lookup table (old pipeline builds the same PSF). The packet makes it visible to an agent.'),
           ('packets/psf_0m4_galaxy_stars_0180.png', 'Two of the six PSF stars lie on the host galaxy NGC 6384.'),
           ('packets/diff_0133.png', 'Target / registered template / difference: SN clean, field-star dipoles reveal a ~0.6 px registration offset.')]
pk_html = ''.join(f'<figure><img src="report/{p}" alt="" loading=lazy><figcaption>{c}</figcaption></figure>'
                  for p, c in packets if (REP / p).exists())
extra_html = ''.join(f'<h3>{k}</h3><p>{v}</p>' for k, v in EXTRA.items())

html = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>snpipe vs lcogtsnpipe</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1f;--mut:#5f6368;--line:#e2e2e0;--acc:#2f6f9f;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151617;--fg:#e8e8e6;--mut:#a0a3a7;--line:#2c2e30;--acc:#7fb3dc;--card:#1d1f21}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1080px;margin:auto;padding:24px 16px 64px}}h1{{font-size:1.8rem;margin:.2em 0}}h2{{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.3em}}
.lead{{color:var(--mut)}}table{{border-collapse:collapse;width:100%;font-size:.92rem;margin:1em 0}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:var(--mut);font-weight:600}}.n{{color:var(--mut);font-size:.85em}}.wrap{{overflow-x:auto}}code{{font-size:.9em}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:1.2em 0}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.card b{{display:block;font-size:1.4rem;color:var(--acc)}}figure{{margin:1.2em 0}}img{{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}}figcaption{{color:var(--mut);font-size:.9rem}}
a{{color:var(--acc)}}
</style></head><body><main>
<h1>snpipe: an IRAF-free lcogtsnpipe, checked against the original on SN 2024pxl</h1>
<p class=lead>Pure-Python rewrite of the LCOGT supernova pipeline for agent-run reductions. Every stage was run with both pipelines on the same LCO frames
(99 frames of 2024-07-22…28) and compared number by number; the light curve is compared with Singh et al. (2026).
<b><a href="stages.html">Stage-by-stage visual report: old vs new, and how an agent checks each stage →</a></b><br>
Code: <a href="https://github.com/yizedong/lcogtsnpipe-ai">github.com/yizedong/lcogtsnpipe-ai</a> · details: <a href="report/README.md">report/README.md</a> · differences from the old code: <a href="decisions.md">decisions.md</a> · agents: <a href="agents.md">agents.md</a></p>
<div class=cards>
<div class=card><b>{f(S.get('mag_ft3', {}).get('median'))} ± {f(S.get('mag_ft3', {}).get('robust_sigma'), sign=False)}</b>calibrated SN mags on difference images, new − old (n={S.get('mag_ft3', {}).get('n', '—')})</div>
<div class=card><b>bit-identical</b>cosmic-ray masks; aperture photometry identical to IRAF</div>
<div class=card><b>2.7–11×</b>faster wall clock (parallel, no IRAF process per image)</div>
<div class=card><b>pip install</b>no IRAF, no MySQL server, no HOTPANTS; PyZOGY bundled</div>
</div>
<h2>Why a new pipeline</h2><p>lcogtsnpipe depends on IRAF (no longer supported by NOAO, hard to install) and a MySQL server, reduces images one at a time, and needs a person to check each step. snpipe keeps the science, runs in pure Python, in parallel, and reports every check in machine-readable form.</p><figure><img src="report/visual/speed.png" alt="speed-up"><figcaption>Same 99 frames, same computer: 8.1 h → 2.5 h (hatched: estimated).</figcaption></figure>
<h2>Stage by stage</h2><div class=wrap><table><tr><th>stage</th><th>old</th><th>new</th><th>new − old (median ± robust σ)</th><th>speed</th></tr>{stage_rows}</table></div>
<p class=n>Frames reduced by only one pipeline: none only-old; 19 only-new in the unsubtracted PSF stage (old PSF failed; recovered by the remediation ladder).</p>
<h2>Light curve vs Singh et al. (2026)</h2>
<div class=wrap><table><tr><th>band</th><th>old − paper</th><th>new − paper</th></tr>{lc_rows}</table></div>
{fig_html}
<h2>How agents check a reduction</h2>
<p>The old pipeline needed a human at <code>checkwcs</code>, <code>checkpsf</code>, <code>zcat -i</code>, <code>checkmag</code>, <code>checkdiff</code> and <code>getmag --show</code>; unattended, it accepts everything.
snpipe gives each stage (1) gates with per-frame QA files and exit codes, (2) the manual's remediation ladder for failed PSFs, (3) review packets and logged verdicts, and (4) an ASTRA record whose decisions expose the old defaults.</p>
{pk_html}
{extra_html}
<h2>Limitations and next steps</h2>
<ul><li>Constant PSF over the frame (as DAOPHOT varorder 0): 6 PSF stars leave 0.02–0.04 mag bias / 0.07–0.10 mag scatter on 1 m frames in both pipelines.</li>
<li>WCS-based registration leaves ~0.6 px offsets between the 2018 templates and 2024 frames; a star-based refinement (as IRAF geomap) is the next step for <code>diff</code>.</li>
<li>PyZOGY's iterative flux-scale fit is sensitive to the star set (cutouts moved SN mags by up to 0.2 mag); a zero-point-based option is being tested.</li>
<li>PSF stars are not checked against the BANZAI bad-pixel mask (neither pipeline).</li></ul>
<h2>Credits</h2><p>Built by <b>Claude (Anthropic, Claude Opus 5.5) in Claude Code</b> — code, IRAF-source analysis, old-pipeline installation,
validation and this report — directed and reviewed by Yize Dong. Based on lcogtsnpipe (S. Valenti et al., MIT), PyZOGY (D. Guevel, MIT) and the SLIDE PyZOGY speed-up idea (Y. Dong).</p>
</main></body></html>"""
(ROOT / 'docs' / 'index.html').write_text(html)
print('wrote', ROOT / 'docs' / 'index.html')
