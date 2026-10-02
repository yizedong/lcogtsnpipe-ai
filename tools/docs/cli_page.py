"""Build docs/reference/cli.md from the snpipe argument parser (so the page can never disagree with the code).

usage: python tools/docs/cli_page.py
"""
import argparse
import contextlib
import io
from pathlib import Path

from snpipe import cli

ROOT = Path(__file__).resolve().parents[2]


def parser():
    """Capture the parser that cli.main builds, without running a command."""
    captured = {}
    real = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        captured['p'] = self
        raise SystemExit(0)
    argparse.ArgumentParser.parse_args = grab
    try:
        with contextlib.suppress(SystemExit):
            cli.main([])
    finally:
        argparse.ArgumentParser.parse_args = real
    return captured['p']


def main():
    p = parser()
    subs = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    helps = {c.dest: c.help for c in subs._choices_actions}
    L = ['# Command reference', '',
         'Generated from the code by `python tools/docs/cli_page.py`. Exit codes of every command: 0 ok, 1 some frames '
         'failed their checks, 2 configuration error, 3 missing input, 4 external service failed.', '']
    groups = [('Whole reductions', ['run', 'status', 'init-target', 'report', 'review-all']),
              ('Setup', ['add-target', 'ingest', 'catalogs']),
              ('Stages', ['wcs', 'cosmic', 'psf', 'psfmag', 'zcat', 'template', 'diff', 'mag', 'getmag']),
              ('Review', ['review', 'verdict'])]
    listed = sum((g for _, g in groups), [])
    groups.append(('Other', [c for c in subs.choices if c not in listed]))
    for title, names in groups:
        names = [n for n in names if n in subs.choices]
        if not names:
            continue
        L += [f'## {title}', '']
        for n in names:
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                subs.choices[n].print_help()
                text = buf.getvalue()
            L += [f'### snpipe {n}', '', helps.get(n) or '', '', '```', text.replace('usage: ', '').rstrip(), '```', '']
    out = ROOT / 'docs' / 'reference' / 'cli.md'
    out.write_text('\n'.join(L))
    print('wrote', out)


if __name__ == '__main__':
    main()
