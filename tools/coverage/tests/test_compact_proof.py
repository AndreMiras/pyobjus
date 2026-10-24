"""Local validation of the small CI helper; retained with the exploratory tools."""

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / ".ci/cython_coverage_proof.py"


@pytest.fixture
def compact_project(spike, tmp_path):
    project = tmp_path / "project"
    shutil.copytree(spike[0] / "project", project)
    return project


def invoke(project, statement):
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    # The committed helper must work without imports from the omitted tools.
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-c", "import pathlib, runpy, sys; p = runpy.run_path(sys.argv[1]); " + statement, str(SCRIPT)],
        cwd=project, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def collect(project):
    result = invoke(project, "sys.exit(p['collect']('pxiprobe', ['test_probe.py', '-q'], pathlib.Path('proof')))")
    return result


def report(project, fresh=False):
    return invoke(project, f"p['report'](pathlib.Path('proof'), {{'declarations.pxi'}}, fresh={fresh})")


def test_compact_proof_matches_the_validated_candidate(compact_project, spike):
    project = compact_project
    result = collect(project)
    assert result.returncode == 0, result.stdout
    result = report(project)
    assert result.returncode == 0, result.stdout
    summary = json.loads((project / "proof/report.json").read_text())
    assert summary["files"] == spike[1]["candidate"]["files"]
    assert summary["inventory"] == spike[1]["candidate"]["inventory"]
    assert summary["totals"] == {"hits": 4, "misses": 19}
    assert summary["files"]["pxiprobe/bridge.pyx"]["misses"] == [1, 5, 8, 9]
    assert summary["files"]["pxiprobe/active.pxi"]["hits"] == [2, 3, 7]
    result = report(project, fresh=True)
    assert result.returncode == 0, result.stdout
    assert json.loads((project / "proof/report.json").read_text()) == summary


def test_compact_proof_preserves_pytest_failure(compact_project):
    project = compact_project
    with (project / "test_probe.py").open("a") as stream:
        stream.write("\ndef test_failure():\n    assert False\n")
    result = collect(project)
    assert result.returncode == 1, result.stdout
    result = report(project)
    assert result.returncode != 0 and "successful collection" in result.stdout
    assert not (project / "proof/coverage.xml").exists()


@pytest.mark.parametrize("source", ["pxiprobe/bridge.c", "pxiprobe/bridge.pyx"])
def test_compact_proof_rejects_changed_inputs(compact_project, source):
    project = compact_project
    result = collect(project)
    assert result.returncode == 0, result.stdout
    with (project / source).open("a") as stream:
        stream.write("\n")
    result = report(project)
    assert result.returncode != 0 and "changed after collection" in result.stdout
    assert not (project / "proof/coverage.xml").exists()


def test_compact_proof_rejects_missing_data(compact_project):
    project = compact_project
    result = collect(project)
    assert result.returncode == 0, result.stdout
    (project / "proof/coverage.data").unlink()
    result = report(project)
    assert result.returncode != 0 and "Collected coverage data is required" in result.stdout
    assert not (project / "proof/coverage.xml").exists()


def test_compact_proof_keeps_last_valid_report_on_check_failure(compact_project):
    project = compact_project
    assert collect(project).returncode == 0
    assert report(project).returncode == 0
    xml = (project / "proof/coverage.xml").read_bytes()
    result = invoke(project, (
        "p['report'](pathlib.Path('proof'), {'declarations.pxi'}, "
        "check=lambda *_: (_ for _ in ()).throw(ValueError('attribution check failed')))"
    ))
    assert result.returncode != 0 and "attribution check failed" in result.stdout
    assert (project / "proof/coverage.xml").read_bytes() == xml
    assert not (project / "proof/coverage.xml.tmp").exists()


def test_compact_inventory_requires_generated_c_and_mapped_sources(compact_project, monkeypatch):
    project = compact_project
    helper = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(project)
    original = helper["inventory"]("pxiprobe", {"declarations.pxi"})
    c_file = project / "pxiprobe/bridge.c"
    saved = c_file.with_suffix(".c.saved")
    c_file.rename(saved)
    with pytest.raises(FileNotFoundError):
        helper["inventory"]("pxiprobe", {"declarations.pxi"})
    saved.rename(c_file)
    assert helper["inventory"]("pxiprobe", {"declarations.pxi"}) == original
    (project / "pxiprobe/orphan.pxi").write_text("def orphan():\n    return 1\n")
    with pytest.raises(ValueError, match="source inventory.*orphan"):
        helper["inventory"]("pxiprobe", {"declarations.pxi"})
