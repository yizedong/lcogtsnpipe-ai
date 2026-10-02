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
           'templates': {'dayobs': '20990601', 'camera': 'fa'}}
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
    assert t['name'] == '2099abc' and t['templates']['frames'] == t['science']['frames']
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'a', science={'dayobs': '2099-01-01', 'frames': 'archive'}))
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'b', templates={'dayobs': '20990601'}))
    monkeypatch.delenv('SNPIPE_RAW', raising=False)
    with pytest.raises(target.TargetError):
        target.load(make_target(tmp_path / 'c', science={'dayobs': '20990101', 'frames': '${SNPIPE_RAW}/x'}))


def test_frames_for_selects_dayobs(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    names = ['cpt1m012-fa06-20990105-0001-e91.fits.fz', 'cpt1m012-fa06-20990401-0001-e91.fits.fz',
             'tfn1m001-fa20-20990601-0001-e91.fits.fz']
    (raw / 'frames.json').write_text(json.dumps([{'filename': n} for n in names]))
    t = target.load(make_target(tmp_path))
    assert [f['filename'] for f in target.frames_for(t, 'science')[0]] == names[:1]
    assert [f['filename'] for f in target.frames_for(t, 'templates')[0]] == names[2:]


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
    for d in sorted((ROOT / 'targets').iterdir()):
        t = target.load(d)
        assert (d / 'universes' / 'baseline.yaml').exists(), d
        assert not target.in_range(t['templates']['dayobs'].split('-')[0], t['science']['dayobs']), d
