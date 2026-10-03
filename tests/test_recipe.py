"""The ASTRA recipe, target files and the executor (no data needed)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from snpipe import run, target

ROOT = Path(__file__).resolve().parents[1]


def make_target(tmp_path, **over):
    d = tmp_path / 'targets' / 'sn2099abc'
    doc = {'name': '2099abc', 'aliases': ['SN2099abc'], 'ra': 10.5, 'dec': -20.25, 'workdir': str(tmp_path / 'work'),
           'science': {'dayobs': '20990101-20990301', 'frames': str(tmp_path / 'raw')},
           'reference': {'dayobs': '20990601', 'camera': 'fa'}}
    doc.update(over)
    (d / 'universes').mkdir(parents=True)
    (d / 'target.yaml').write_text(yaml.safe_dump(doc))
    shutil.copy(run.recipe_dir() / 'universes' / 'baseline.yaml', d / 'universes' / 'baseline.yaml')
    return d


def test_recipe_is_packaged_and_linked():
    assert (run.recipe_dir() / 'astra.yaml').exists()
    assert (ROOT / 'pipeline' / 'astra.yaml').resolve() == (run.recipe_dir() / 'astra.yaml').resolve()


def test_recipe_validates_with_astra():
    astra = shutil.which('astra')
    if not astra:
        pytest.skip('astra-tools not installed')
    r = subprocess.run([astra, 'validate', str(run.recipe_dir() / 'astra.yaml')], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_baseline_selects_every_default():
    a = run.load_analysis()
    base = yaml.safe_load((run.recipe_dir() / 'universes' / 'baseline.yaml').read_text())['decisions']
    assert base == {k: v['default'] for k, v in a['decisions'].items()}


def test_plan_orders_by_inputs_and_honours_when():
    a = run.load_analysis()
    base = {k: v['default'] for k, v in a['decisions'].items()}
    ids = [s['id'] for s in run.plan(a, base)]
    pos = {s: i for i, s in enumerate(ids)}
    for s in a['outputs']:
        if s['id'] in pos:
            assert all(pos[i] < pos[s['id']] for i in s.get('inputs', []) if i in pos), s['id']
    assert 'wcs_science' not in ids and ids[-1] == 'report'
    assert 'wcs_science' in [s['id'] for s in run.plan(a, {**base, 'wcs_check': 'gaia'})]


def test_universe_errors():
    a = run.load_analysis()
    base = {k: v['default'] for k, v in a['decisions'].items()}
    with pytest.raises(target.TargetError):
        run.plan(a, {k: v for k, v in base.items() if k != 'psf_model'})
    with pytest.raises(target.TargetError):
        run.plan(a, {**base, 'psf_model': 'nonsense'})


def test_expand_fills_every_placeholder():
    step = {'id': 'x', 'inputs': ['target', 'y'], 'decisions': ['d']}
    cmd = run.expand('a {inputs.target} {inputs.y} --d {decisions.d} -o {output} {{literal}}', step,
                     {'target': '/t.yaml', 'y': '/y.json'}, {'d': 'opt'}, '/out.json')
    assert cmd == 'a /t.yaml /y.json --d opt -o /out.json {literal}'
    with pytest.raises(target.TargetError):
        run.expand('a {decisions.other}', step, {}, {'d': 'opt'}, '/o')


def test_target_file_validation(tmp_path, monkeypatch):
    t = target.load(make_target(tmp_path))
    assert t['name'] == '2099abc' and t['reference']['1m0']['frames'] == t['science']['frames']
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'a', science={'dayobs': '2099-01-01', 'frames': 'archive'}))
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'b', reference={'dayobs': '20990601'}))
    monkeypatch.delenv('SNPIPE_RAW', raising=False)
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'c', science={'dayobs': '20990101', 'frames': '${SNPIPE_RAW}/x'}))


def test_frames_for_selects_dayobs(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    names = ['cpt1m012-fa06-20990105-0001-e91.fits.fz', 'cpt1m012-fa06-20990401-0001-e91.fits.fz',
             'tfn1m001-fa20-20990601-0001-e91.fits.fz', 'tfn0m414-sq31-20990601-0001-e91.fits.fz']
    (raw / 'frames.json').write_text(json.dumps([{'filename': n} for n in names]))
    t = target.load(make_target(tmp_path))
    assert [f['filename'] for f in target.frames_for(t, 'science')[0]] == names[:1]
    assert [f['filename'] for f in target.frames_for(t, 'reference')[0]] == names[2:3]   # 1m0 reference only


def test_dry_run_does_not_touch_anything(tmp_path):
    d = make_target(tmp_path)
    lines = []
    summary, rc = run.run(d, dry_run=True, echo=lines.append)
    assert rc == 0 and set(summary.values()) == {'would run'}
    assert not (tmp_path / 'work').exists()
    assert any('snpipe report --target-file' in line for line in lines)


def test_example_targets_load(monkeypatch):
    monkeypatch.setenv('SNPIPE_RAW', '/raw')
    monkeypatch.setenv('SNPIPE_WORK', '/work')
    for d in sorted(p for p in (ROOT / 'targets').iterdir() if p.is_dir()):
        t = target.load(d)
        assert (d / 'universes' / 'baseline.yaml').exists(), d
        assert t['reference'], d


def test_schema_errors(tmp_path):
    bad = [dict(colour='red'),                                                   # unknown key
           dict(science={'dayobs': '20990230', 'frames': 'archive'}),            # no such date
           dict(science={'dayobs': '20990301-20990101', 'frames': 'archive'}),   # reversed range
           dict(reference={'dayobs': '20990201', 'camera': 'fa'}),               # inside the science range
           dict(resources={'jobs': 0}),                                          # not positive
           dict(schema_version=2)]
    for i, over in enumerate(bad):
        with pytest.raises(target.TargetError):
            target.load(make_target(tmp_path / str(i), **over))
    old = make_target(tmp_path / 'old', reference=None, templates={'dayobs': '20990601', 'camera': 'fa'})
    assert target.load(old)['reference']['1m0']['camera'] == 'fa'                # old key still accepted


def test_no_reference_keeps_report(tmp_path):
    d = make_target(tmp_path, reference=None)
    lines = []
    summary, rc = run.run(d, dry_run=True, echo=lines.append)
    assert rc == 0 and 'lc_unsubtracted' in summary and 'report' in summary and 'review_queue' in summary
    assert not any(k in summary for k in ('ingest_reference', 'diff_science', 'lc_subtracted', 'psf_reference'))


def test_signature_follows_target_facts_not_resources(tmp_path):
    sci = {'dayobs': '20990101-20990301', 'frames': str(tmp_path / 'raw')}
    t1 = target.load(make_target(tmp_path / 'a', science=sci))
    t2 = target.load(make_target(tmp_path / 'b', science=sci, resources={'jobs': 3}, workdir=str(tmp_path / 'w2')))
    t3 = target.load(make_target(tmp_path / 'c', science=sci, ra=11.0))
    assert target.facts(t1) == target.facts(t2) != target.facts(t3)


def test_cli_defaults_match_recipe_defaults():
    """A decision's default in pipeline/astra.yaml must be the CLI default, or the two would silently drift."""
    from snpipe import cli
    a = run.load_analysis()
    default = {k: v['default'] for k, v in a['decisions'].items()}
    p = cli.parser()
    sub = next(x for x in p._actions if x.__class__.__name__ == '_SubParsersAction').choices
    get = lambda cmd, opt: next(x.default for x in sub[cmd]._actions if opt in x.option_strings)
    conv = lambda cmd, opt: next(x.type for x in sub[cmd]._actions if opt in x.option_strings)
    assert get('psf', '--model') == default['psf_model']
    assert get('psf', '--auto-fix') == default['psf_auto_fix']
    assert get('psf', '--nstars') == conv('psf', '--nstars')(default['psf_nstars'])
    assert get('psf', '--max-apercorr') == conv('psf', '--max-apercorr')(default['max_apercorr'])
    assert get('diff', '--normalize') == default['diff_normalize']
    assert get('diff', '--register') == default['diff_register']
    assert get('diff', '--region') == default['diff_region']
    assert get('diff', '--gain') == default['diff_gain']
    assert get('catalogs', '--sloan-source') == default['sloan_source']
    assert get('diff', '--reference-class') == default['diff_reference_class']


def test_step_ids_follow_stage_role():
    a = run.load_analysis()
    products = {'target_registered', 'catalogs', 'lc_unsubtracted', 'lc_subtracted', 'review_queue', 'report'}
    for o in a['outputs']:
        if o['id'] in products:
            continue
        stage, role = o['recipe']['command'].split()[1], o['id'].split('_', 1)[1]
        assert o['id'].startswith(stage + '_'), o['id']
        assert role.split('_')[0] in ('science', 'reference', 'difference'), o['id']


def test_reference_per_class(tmp_path):
    t = target.load(make_target(tmp_path / 'a', reference={'1m0': {'dayobs': '20990601', 'camera': 'fa'},
                                                           '0m4': {'dayobs': '20990602', 'camera': 'sq'}}))
    assert set(t['reference']) == {'1m0', '0m4'}
    with pytest.raises(target.TargetError):          # not a telescope class
        target.load(make_target(tmp_path / 'b', reference={'1m': {'dayobs': '20990601', 'camera': 'fa'}}))
    with pytest.raises(target.TargetError):          # single reference with a camera of unknown class
        target.load(make_target(tmp_path / 'c', reference={'dayobs': '20990601', 'camera': 'kb'}))


def test_pick_reference_same_class_by_default():
    from snpipe.diff import pick_reference
    refs = {'1m0': {'dayobs': '20990601', 'camera': 'fa'}}
    assert pick_reference('cpt1m012-fa06-20990105-0001-e91.fits', refs) == ('1m0', refs['1m0'])
    assert pick_reference('tfn0m414-sq31-20990105-0001-e91.fits', refs) == ('0m4', None)
    assert pick_reference('tfn0m414-sq31-20990105-0001-e91.fits', refs, 'any') == ('1m0', refs['1m0'])


def test_cross_class_differences_are_not_selected_by_default():
    from snpipe.selection import cross_class
    assert cross_class('tfn0m419-sq32-20250720-0152-e91.optimal.fa.diff.fits')        # 0.4-m minus 1-m reference
    assert not cross_class('cpt1m010-fa14-20250715-0303-e91.optimal.fa.diff.fits')    # 1 m minus 1 m
    assert not cross_class('elp1m008-fa16-20240907-0115-e91.optimal.fl.diff.fits')    # fa science, fl reference: both 1 m
    assert not cross_class('cpt1m010-fa14-20250715-0303-e91.fits')                    # not a difference image


def test_survey_reference(tmp_path):
    from snpipe import survey
    t = target.load(make_target(tmp_path / 'a', reference={'1m0': {'survey': 'ps1'},
                                                           '0m4': {'dayobs': '20990601', 'camera': 'sq'}}))
    assert t['reference']['1m0']['survey'] == 'ps1' and t['reference']['1m0']['camera'] == 'ps1'
    for bad in ({'1m0': {'survey': 'des'}}, {'1m0': {'survey': 'ps1', 'dayobs': '20990601'}}, {'survey': 'ps1'}):
        with pytest.raises(target.TargetError):
            target.load(make_target(tmp_path / str(len(str(bad))), reference=bad))
    assert survey.ps1_band('rp') == 'r'
    with pytest.raises(survey.SurveyError):
        survey.ps1_band('B')                     # PS1 has no B, V, U


def test_exit_code_missing_only_when_nothing_could_run():
    from snpipe import qa
    s = lambda ok, skipped, missing: {'counts': {'ok': ok, 'warn': 0, 'fail': 0, 'skipped': skipped},
                                      'skipped_missing_input': ['f'] * missing}
    assert qa.exit_code(s(0, 749, 3)) == qa.EXIT['ok']               # 746 already done, 3 without psf
    assert qa.exit_code(s(0, 5, 5)) == qa.EXIT['missing_input']      # nothing could run
    assert qa.exit_code(s(2, 3, 3)) == qa.EXIT['ok']


def test_diff_variant_selection():
    import argparse
    from snpipe import selection
    names = ['cpt1m010-fa14-20250715-0303-e91.optimal.fa.diff.fits', 'cpt1m010-fa14-20250715-0303-e91.optimal.fa.fit.diff.fits',
             'cpt1m010-fa14-20250715-0303-e91.optimal.fa.zp.diff.fits', 'tfn0m419-sq32-20250720-0152-e91.optimal.fa.diff.fits']
    rows = [{'filename': n} for n in names]
    pick = lambda v: [r['filename'] for r in rows if selection.keep_frame(r['filename'], v)]
    assert pick(None) == names[:1]                              # default: zero-point gain, full frame, same class
    assert pick('fit:full:same') == names[1:2]
    assert pick('zeropoint:full:any') == [names[0], names[3]]
