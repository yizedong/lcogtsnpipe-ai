"""Build docs/reference/recipe.md from pipeline/astra.yaml: every step and every decision, in one readable page.

usage: python tools/docs/recipe_page.py
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    a = yaml.safe_load((ROOT / 'src' / 'snpipe' / 'pipeline' / 'astra.yaml').read_text())
    L = ['# The recipe', '',
         f"Generated from [pipeline/astra.yaml](../../pipeline/astra.yaml) by `python tools/docs/recipe_page.py`. "
         f"{len(a['outputs'])} steps, {len(a['decisions'])} decisions. Step ids are `<stage>_<role>` (role: science, "
         'reference, difference); the deliverables are named for what they are.', '',
         '## Steps', '', '| step | stage | needs | decisions | what it does |', '|---|---|---|---|---|']
    for o in a['outputs']:
        stage = o['recipe']['command'].split()[1]
        when = f" (only with {', '.join(o['when'])})" if o.get('when') else ''
        needs = ', '.join(i for i in o.get('inputs', []) if i != 'target')
        L.append(f"| `{o['id']}` | {stage} | {needs} | {', '.join(o.get('decisions', []))} | "
                 f"{' '.join(o['description'].split())}{when} |")
    L += ['', '## Decisions', '', 'The baseline universe selects every default.', '']
    for k, d in a['decisions'].items():
        L += [f"### `{k}`: {d['label']}", '', ' '.join(d.get('rationale', '').split()), '']
        for oid, opt in d['options'].items():
            L.append(f"- `{oid}`{' **(default)**' if oid == d.get('default') else ''}: {opt['label']}")
        L.append('')
    out = ROOT / 'docs' / 'reference' / 'recipe.md'
    out.write_text('\n'.join(L))
    print('wrote', out)


if __name__ == '__main__':
    main()
