"""Contract mutations must fail the behavioral scheduler tests."""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
source = (root / 'site/compute-scheduler.js').read_text()
tests = (root / 'tests/compute/scheduler.test.cjs').read_text()
mutations = {
    'global_cap': ('this.active.size<this.maxWorkers', 'this.active.size<100'),
    'background_cap': ("||[...this.active].some(x=>x.kind==='background')", ''),
    'priority': ('classes.indexOf(a.kind)-classes.indexOf(b.kind)', 'classes.indexOf(b.kind)-classes.indexOf(a.kind)'),
    'training_pause': ('this.holds.size>0||', ''),
}
with tempfile.TemporaryDirectory(prefix='compute-mutations-') as tmp:
    for name, (old, new) in mutations.items():
        assert old in source, name
        scheduler = pathlib.Path(tmp) / 'scheduler.cjs'
        scheduler.write_text(source.replace(old, new))
        test = pathlib.Path(tmp) / 'scheduler.test.cjs'
        test.write_text(tests.replace("'../../site/compute-scheduler.js'", repr(str(scheduler))))
        result = subprocess.run(['node', '--test', '--test-isolation=none', str(test)], cwd=root, capture_output=True, text=True)
        assert result.returncode != 0, f'Surviving mutation: {name}'
        assert 'AssertionError' in result.stdout + result.stderr, result.stdout + result.stderr
        print(f'Killed: {name}')
