"""Build docs/reference/bugs.md (GitHub) and docs/bugs.html (website) from the ledger docs/reference/bugs.json.

usage: python tools/docs/bugs_page.py
Every bug-fix PR adds or updates an entry in docs/reference/bugs.json and reruns this.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
L = json.loads((ROOT / 'docs' / 'reference' / 'bugs.json').read_text())
BUGS = L['bugs']
REPO = 'https://github.com/yizedong/lcogtsnpipe-ai/commit/'
ORIGIN = {'old': 'also in the old pipeline', 'new': 'snpipe only', 'ops': 'run scripts', 'docs': 'documentation'}
SECTIONS = [
    ('fixed', 'old', 'Fixed: bugs inherited from the old pipeline',
     'These are in lcogtsnpipe too, so old and new agreed while both were wrong. Fixing them makes snpipe '
     'differ from the old pipeline on purpose.'),
    ('fixed', 'new', 'Fixed: bugs in the new code',
     'Mistakes made while porting, found by comparing with the old pipeline/IRAF, by tests on real data, or by review.'),
    ('open', None, 'Open: verified, not fixed yet', 'Checked to be real; effect on SN 2024pxl given.'),
    ('not-a-bug', None, 'Checked and not bugs', 'Reported as possible bugs; checked and found to be fine.'),
]


def pick(status, origin):
    return [b for b in BUGS if b['status'] == status and (origin is None or b['origin'] == origin)]


def counts():
    n = {s: len([b for b in BUGS if b['status'] == s]) for s in ('fixed', 'open', 'not-a-bug')}
    inh = len([b for b in BUGS if b['status'] == 'fixed' and b['origin'] == 'old'])
    return n, inh


# ---- Markdown -------------------------------------------------------------------------------------------
def md_entry(b):
    commit = f" · fix [`{b['commit']}`]({REPO}{b['commit']})" if b.get('commit') else ''
    date = f" · {b['date']}" if b.get('date') else ''
    out = [f"### {b['id']} — {b['title']}",
           f"*{b['stage']} · {ORIGIN[b['origin']]}{date}{commit} · found by: {b['found_by']}*", '',
           f"- **Where:** {b['where']}", f"- **What was wrong:** {b['what']}", f"- **Why it matters:** {b['why']}"]
    if b['fix'] != '-':
        out.append(f"- **{'Fix' if b['status'] == 'fixed' else 'Proposed fix'}:** {b['fix']}")
    if b['effect'] != '-':
        out.append(f"- **Effect on SN 2024pxl:** {b['effect']}")
    return '\n'.join(out) + '\n'


n, inh = counts()
md = ['# Bugs fixed, and why', '',
      f"{n['fixed']} fixed ({inh} of them inherited from the old pipeline), {n['open']} open, "
      f"{n['not-a-bug']} checked and not bugs. Generated from [bugs.json](bugs.json) by `tools/docs/bugs_page.py`; "
      'other deliberate differences from the old pipeline are in [compatibility.md](compatibility.md).', '',
      '| id | status | origin | stage | bug |', '|---|---|---|---|---|']
md += [f"| {b['id']} | {b['status']} | {ORIGIN[b['origin']]} | {b['stage']} | {b['title']} |" for b in BUGS]
for status, origin, title, lead in SECTIONS:
    md += ['', f'## {title}', '', lead, '']
    md += [md_entry(b) for b in pick(status, origin)]
(ROOT / 'docs' / 'reference' / 'bugs.md').write_text('\n'.join(md))

# ---- HTML -----------------------------------------------------------------------------------------------
e = html.escape


def html_entry(b):
    commit = f" · fix <a href='{REPO}{b['commit']}'><code>{b['commit']}</code></a>" if b.get('commit') else ''
    date = f" · {b['date']}" if b.get('date') else ''
    rows = [('Where', f"<code>{e(b['where'])}</code>"), ('What was wrong', e(b['what'])), ('Why it matters', e(b['why']))]
    if b['fix'] != '-':
        rows.append(('Fix' if b['status'] == 'fixed' else 'Proposed fix', e(b['fix'])))
    if b['effect'] != '-':
        rows.append(('Effect on SN 2024pxl', e(b['effect'])))
    dl = ''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)
    return (f"<article id={b['id']} class='bug {b['status']}'><h3><span class=id>{b['id']}</span> {e(b['title'])}</h3>"
            f"<p class=meta><span class='tag {b['origin']}'>{ORIGIN[b['origin']]}</span>{e(b['stage'])}{date}{commit}"
            f" · found by {e(b['found_by'])}</p><dl>{dl}</dl></article>")


body = ''
for status, origin, title, lead in SECTIONS:
    items = pick(status, origin)
    body += f"<h2>{title} <span class=n>({len(items)})</span></h2><p class=lead>{lead}</p>" + ''.join(map(html_entry, items))
toc = ''.join(f"<a href='#{b['id']}' class='{b['status']}'>{b['id']}</a>" for b in BUGS)

page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Bug ledger</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1f;--mut:#5f6368;--line:#e2e2e0;--acc:#0b6e99;--card:#fff;--old:#8a5a00;--ok:#2a7d3a;--open:#b03a2e}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#151617;--fg:#e8e8e6;--mut:#a0a3a7;--line:#2c2e30;--acc:#7fb3dc;--card:#1d1f21;--old:#d9a441;--ok:#6cc47a;--open:#e8796d}}}}
:root[data-theme=dark]{{--bg:#151617;--fg:#e8e8e6;--mut:#a0a3a7;--line:#2c2e30;--acc:#7fb3dc;--card:#1d1f21;--old:#d9a441;--ok:#6cc47a;--open:#e8796d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:980px;margin:auto;padding:24px 16px 64px}}h1{{font-size:1.8rem;margin:.2em 0}}
h2{{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.3em}}h3{{font-size:1.05rem;margin:0 0 .2em}}
.lead,.meta,.n{{color:var(--mut)}}.meta{{font-size:.88rem;margin:0 0 .5em}}a{{color:var(--acc)}}code{{font-size:.88em;overflow-wrap:anywhere}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin:1em 0}}.stats div{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px}}
.stats b{{font-size:1.4rem;display:block}}
.toc{{display:flex;flex-wrap:wrap;gap:6px;margin:1em 0}}.toc a{{border:1px solid var(--line);border-radius:999px;padding:1px 10px;text-decoration:none;color:var(--fg);background:var(--card);font-size:.85rem}}
.toc a.fixed{{border-color:var(--ok)}}.toc a.open{{border-color:var(--open)}}
.bug{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:12px 16px;margin:12px 0}}
.bug.fixed{{border-left-color:var(--ok)}}.bug.open{{border-left-color:var(--open)}}
.id{{color:var(--mut);font-weight:600;margin-right:6px}}
.tag{{display:inline-block;font-size:.72rem;font-weight:700;border:1px solid var(--mut);color:var(--mut);border-radius:4px;padding:0 6px;margin-right:8px}}
.tag.old{{border-color:var(--old);color:var(--old)}}
dl{{display:grid;grid-template-columns:150px 1fr;gap:4px 14px;margin:0;font-size:.94rem}}dt{{color:var(--mut)}}dd{{margin:0}}
@media (max-width:640px){{dl{{grid-template-columns:1fr}}dt{{margin-top:6px}}}}
</style></head><body><main>
<p><a href="index.html">← summary</a></p>
<h1>Bugs fixed, and why</h1>
<p class=lead>Every bug found in snpipe or inherited from lcogtsnpipe: what was wrong, why it matters, the fix, and its measured effect on
the SN 2024pxl reduction. Other deliberate differences from the old pipeline: <a href="reference/compatibility.md">compatibility.md</a>.
Generated from <a href="reference/bugs.json">bugs.json</a> by <code>tools/docs/bugs_page.py</code>.</p>
<div class=stats><div><b>{n['fixed']}</b>fixed</div><div><b>{inh}</b>of them inherited from the old pipeline</div>
<div><b>{n['open']}</b>open (verified)</div><div><b>{n['not-a-bug']}</b>checked, not bugs</div></div>
<nav class=toc>{toc}</nav>
{body}
</main></body></html>"""
(ROOT / 'docs' / 'bugs.html').write_text(page)
print('wrote docs/reference/bugs.md, docs/bugs.html')
