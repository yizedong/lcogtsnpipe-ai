"""Build docs/stages.html: one section per stage — old vs new, and how the agent checks it.

usage: python tools/stage_page.py   (after tools/stage_report.py and tools/compare.py)
Numbers come from docs/report/summary.json (old vs new) and docs/report/stages/stages.json (QA counts).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / 'docs' / 'report'
S = json.loads((REP / 'summary.json').read_text())
Q = json.loads((REP / 'stages' / 'stages.json').read_text())


def ms(key, d=3):
    s = S.get(key, {})
    if not isinstance(s.get('median'), (int, float)):
        return '—'
    return f"{s['median']:+.{d}f} ± {s['robust_sigma']:.{d}f} mag (n={s.get('n', '—')})"


def q(stage, key, default='—'):
    return Q.get(stage, {}).get(key, default)


# (id, title, what it does, old, new, agreement, figure, extra figures, gates [(check, limit, on failure)])
STAGES = [
    ('cosmic', 'Cosmic rays', 'Find and mask cosmic-ray hits in every image.',
     'astroscrappy', 'the same astroscrappy call',
     f"<b>bit-identical</b> masks: {q('cosmic', 'differ')} pixels differ in the frame shown; 18/18 frames identical",
     'cosmic.png', [],
     [('fraction of pixels flagged', '≤ 1 %', 'warn → review packet (likely a bad frame, e.g. trails or saturation)')]),
    ('wcs', 'Astrometry (WCS)', 'Check where each image points on the sky.',
     'trusts the BANZAI WCS; a person runs <code>checkwcs</code>', 'measures every frame against Gaia DR3, refits if bad',
     f"new check (none before); median rms {q('wcs', 'rms_med', 0):.2f}″ on the {q('wcs', 'n')} templates checked",
     'wcs.png', [],
     [('matched Gaia stars', '≥ 10', 'refit; fail if still too few'),
      ('rms of the match', '≤ 2″', 'refit, then fail'), ('median offset', '≤ 1″', 'refit, then fail')]),
    ('psf', 'PSF model', 'Measure the shape of stars (the PSF) and the aperture correction.',
     'IRAF daophot <code>phot</code>, <code>psf</code>, <code>group</code>, <code>nstar</code>',
     'photutils with the same DAOPHOT recipe (Gaussian + look-up table, grouping, fitted sky)',
     f"aperture correction {ms('apercorr')}; aperture photometry identical to IRAF (0.000)",
     'psf.png', [('psf_ladder.png', 'When the gate fails, the agent reruns the PSF with the fixes listed in the manual '
                  '(larger FWHM, lower saturation level, more stars, another catalog) and checks again. This frame '
                  '(7″ seeing) failed every attempt, so it goes to review instead of into the light curve.'),
                 ('../packets/psf_companion_0087.png', 'Review packet: PSF star 1 has a companion 10 px south '
                  'that leaves a ghost in the model. The old pipeline builds the same PSF; here it is visible to a reviewer.')],
     [('|aperture correction|', '≤ 0.1 mag (old limit)', 'remediation ladder → recheck → review if still failing'),
      ('PSF FWHM vs other frames of the night', 'ensemble outlier', 'review packet')]),
    ('psfmag', 'SN photometry', 'Fit the PSF to the supernova and measure its brightness.',
     'lscsn + daophot <code>allstar</code>', 'photutils PSF fit, IRAF-style sky and background',
     f"SN PSF magnitude {ms('psfmag_ft1')}",
     'psfmag.png', [('../packets/psfmag_0133.png', 'Review packet: SN stamp, fit and residual.')],
     [('how far the fit moved from the SN position', '≤ max(2 px, FWHM/2)', 'warn → review packet'),
      ('spread between fit iterations', '≤ 0.05 mag', 'warn → review packet')]),
    ('zcat', 'Zero points', 'Compare field stars with a catalog to get the zero point and colour term.',
     'Python (zcat)', 'the same code, ported line by line',
     f"zero point {ms('z1_ft1')}",
     'zcat.png', [],
     [('calibration stars kept after clipping', '≥ 5', 'warn → review; frame not calibrated if none')]),
    ('diff', 'Image subtraction', 'Subtract a pre-explosion template so only the supernova is left.',
     'IRAF geomap + gregister, then PyZOGY', 'flux-conserving reprojection, then the same PyZOGY (bad-pixel fill 60× faster)',
     f"SN aperture mag on differences {ms('apmag_ft3')}. The noise check finds {q('diff', 'fail')} of {q('diff', 'n')} "
     "new differences failed (PyZOGY's flux-scale fit); of the 8 such frames in the subset, the old pipeline also has "
     "no magnitude for 7. Failed frames are dropped from the light curve; the zero-point flux scale "
     "(<code>--gain zeropoint</code>) is being tested on them.",
     'diff.png', [('../packets/diff_0133.png', 'Review packet: target, registered template and difference. '
                   'Field stars leave small dipoles, a ~0.6 px registration offset (next improvement).')],
     [('noise of difference / noise of template', '≤ 10 (warn > 5)', 'fail: the flux-scale fit went wrong (seen: 20×)'),
      ('masked fraction', '≤ 50 %', 'warn')]),
    ('mag', 'Calibrated magnitudes', 'Apply zero points and colour terms to get the final magnitude.',
     'calibratemag', 'ported',
     f"SN calibrated mag on differences {ms('mag_ft3')}",
     'mag.png', [],
     [('difference mag − unsubtracted mag', '≥ −0.2 mag', 'fail: the SN cannot be brighter after removing the galaxy')]),
    ('getmag', 'Light curve', 'Collect all points into the light curve.',
     'getmag; a person looks at the plot (<code>--show</code>)', 'getmag + automatic outlier flags; CSV + ECSV with frame names',
     f"{q('getmag', 'n')} points; {q('getmag', 'flagged')} flagged for review",
     'getmag.png', [],
     [('deviation from running median (±1.5 d, same band)', '≤ max(5σ, 5×error, 0.1 mag)', 'flagged, kept in the table for review')]),
]


def section(sid, title, what, old, new, agree, fig, extras, gates):
    rows = ''.join(f'<tr><td>{c}</td><td>{lim}</td><td>{act}</td></tr>' for c, lim, act in gates)
    ex = ''.join(f'<figure class=small><img src="report/stages/{p}" alt="" loading=lazy><figcaption>{c}</figcaption></figure>'
                 for p, c in extras if (REP / 'stages' / p).exists())
    return f"""<section id={sid}><h2>{title}</h2><p class=what>{what}</p>
<div class=cmp><div><span class=tag>old</span>{old}</div><div><span class="tag new">new</span>{new}</div></div>
<p class=agree>{agree}</p>
<figure><img src="report/stages/{fig}" alt="{title}: old vs new and agent check" loading=lazy>
<figcaption>Left: old vs new. Right: what the agent checks on every frame (dashed red = gate).</figcaption></figure>
<h3>How the agent checks it</h3><div class=wrap><table><tr><th>check</th><th>limit</th><th>if it fails</th></tr>{rows}</table></div>
{ex}</section>"""


toc = ''.join(f'<a href="#{s[0]}">{s[1]}</a>' for s in STAGES)
body = ''.join(section(*s) for s in STAGES)
html = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>snpipe stage report</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1f;--mut:#5f6368;--line:#e2e2e0;--acc:#0b6e99;--card:#fff;--old:#8a8a8a;--ok:#2a9d3a;--warn:#c98a00;--fail:#c0392b}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#151617;--fg:#e8e8e6;--mut:#a0a3a7;--line:#2c2e30;--acc:#7fb3dc;--card:#1d1f21}}}}
:root[data-theme=dark]{{--bg:#151617;--fg:#e8e8e6;--mut:#a0a3a7;--line:#2c2e30;--acc:#7fb3dc;--card:#1d1f21}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:auto;padding:24px 16px 64px}}h1{{font-size:1.8rem;margin:.2em 0}}
h2{{margin-top:2.4em;border-bottom:1px solid var(--line);padding-bottom:.3em}}h3{{font-size:1rem;margin:1.4em 0 .3em}}
.lead,.what{{color:var(--mut)}}.toc{{display:flex;flex-wrap:wrap;gap:8px;margin:1em 0}}.toc a{{border:1px solid var(--line);border-radius:999px;padding:3px 12px;text-decoration:none;color:var(--fg);background:var(--card);font-size:.92rem}}
.cmp{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.cmp div{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:.93rem}}
.tag{{display:inline-block;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#fff;background:var(--old);border-radius:4px;padding:1px 6px;margin-right:8px}}.tag.new{{background:var(--acc)}}
.agree{{border-left:3px solid var(--acc);padding-left:10px}}
table{{border-collapse:collapse;width:100%;font-size:.92rem}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}th{{color:var(--mut);font-weight:600}}
.wrap{{overflow-x:auto}}figure{{margin:1em 0}}figure.small img{{max-width:720px}}img{{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}}figcaption{{color:var(--mut);font-size:.9rem}}
.loop{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:1em 0;font-size:.92rem}}.loop span{{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 10px}}
.loop i{{color:var(--mut);font-style:normal}}.ok{{border-color:var(--ok)!important}}.warn{{border-color:var(--warn)!important}}.fail{{border-color:var(--fail)!important}}
a{{color:var(--acc)}}code{{font-size:.9em}}.n{{color:var(--mut);font-size:.88rem}}
@media (max-width:640px){{.cmp{{grid-template-columns:1fr}}}}
</style></head><body><main>
<p><a href="index.html">← summary</a></p>
<h1>Stage by stage: old vs new, and how an agent checks it</h1>
<p class=lead>SN 2024pxl, LCO 1 m and 0.4 m images. Both pipelines reduced the same 99 frames of 2024-07-22…28; snpipe also reduced the
whole season. Every figure is made from the products on disk by <code>tools/stage_report.py</code>.</p>
<h3>The check loop (replaces a person at <code>checkpsf</code>, <code>checkdiff</code>, <code>getmag --show</code>…)</h3>
<div class=loop><span>run stage</span><i>→</i><span>gates on every frame</span><i>→</i><span class=ok>ok: continue</span>
<span class=warn>warn: review packet → agent verdict</span><span class=fail>fail: fix-up ladder → re-check → still failing: review</span></div>
<p class=n>Each frame gets a <code>&lt;frame&gt;.&lt;stage&gt;.qa.json</code> with metrics, limits and status; each verdict is logged in
<code>review/verdicts.jsonl</code>. Details: <a href="agents.md">agents.md</a>.</p>
<nav class=toc>{toc}</nav>
{body}
<h2>Credits</h2><p>Built by <b>Claude (Anthropic, Claude Opus 5.5) in Claude Code</b>, directed and reviewed by Yize Dong.</p>
</main></body></html>"""
(ROOT / 'docs' / 'stages.html').write_text(html)
print('wrote', ROOT / 'docs' / 'stages.html')


# the same content as Markdown, so GitHub shows it directly (docs/report/stages.md)
import re  # noqa: E402


def md(x):
    x = re.sub(r'</?b>', '**', x)
    return re.sub(r'<code>(.*?)</code>', r'`\1`', x)


lines = ['# Stage by stage: old vs new, and how an agent checks it', '',
         'SN 2024pxl. Both pipelines reduced the same 99 frames of 2024-07-22…28; snpipe also reduced the whole season. '
         'Figures: `tools/stage_report.py`. Web version: [docs/stages.html](../stages.html).', '',
         '**Check loop** (replaces a person at `checkpsf`, `checkdiff`, `getmag --show`…): run stage → gates on every frame → '
         'ok: continue · warn: review packet → agent verdict · fail: fix-up ladder → re-check → still failing: review. '
         'Each frame gets `<frame>.<stage>.qa.json`; verdicts go to `review/verdicts.jsonl` ([agents.md](../agents.md)).', '',
         ' · '.join(f'[{t}](#{t.lower().replace(" ", "-").replace("(", "").replace(")", "")})' for _, t, *_ in STAGES), '']
for sid, title, what, old, new, agree, fig, extras, gates in STAGES:
    lines += [f'## {title}', '', what, '', f'| | |\n|---|---|\n| **old** | {md(old)} |\n| **new** | {md(new)} |', '',
              f'> {md(agree)}', '', f'![{title}](stages/{fig})', '',
              '*Left: old vs new. Right: what the agent checks on every frame (dashed red = gate).*', '',
              '**How the agent checks it**', '', '| check | limit | if it fails |', '|---|---|---|']
    lines += [f'| {c} | {lim} | {act} |' for c, lim, act in gates]
    lines.append('')
    for p_, c in extras:
        if (REP / 'stages' / p_).exists():
            lines += [f'![](stages/{p_})', '', f'*{c}*', '']
(REP / 'stages.md').write_text('\n'.join(lines))
print('wrote', REP / 'stages.md')
