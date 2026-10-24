import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from coverage import CoverageData
import pytest

from tools.coverage.report import discover_inventory, seed_and_report, validate_collection


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def runner_project(spike, tmp_path):
    project = tmp_path / "project"
    shutil.copytree(spike[0] / "project", project)
    policy = json.loads((ROOT / "tools/coverage/policy.json").read_text())
    policy.update(
        package="pxiprobe", bootstrap=["pxiprobe"], extension="pxiprobe.bridge",
        empty_sources=["pxiprobe/declarations.pxi"],
        executable_sources=[f"pxiprobe/{name}" for name in (
            "bridge.pyx", "active.pxi", "inactive.pxi", "cold.pyx", "cold_impl.pxi",
        )],
    )
    (project / "policy.json").write_text(json.dumps(policy))
    return project


def invoke(project, arguments):
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    return subprocess.run(
        [sys.executable, *arguments], cwd=project, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def run_fixture(project):
    return invoke(project, [
        "-m", "tools.coverage.run", "--policy", "policy.json", "--config", "coverage.ini",
        "--data-file", ".coverage.runner", "--metadata", "collection.json", "--", "test_probe.py", "-q",
    ])


def report_fixture(project, *arguments):
    return invoke(project, [
        "-m", "tools.coverage.report", "--policy", "policy.json", "--config", "coverage.ini",
        "--data-file", ".coverage.runner", "--metadata", "collection.json",
        "--output", "runner.xml", *arguments,
    ])


def test_policy_runner_matches_accepted_candidate_and_supports_fresh_artifacts(runner_project, spike):
    project = runner_project
    collected = run_fixture(project)
    assert collected.returncode == 0, collected.stdout
    report_command = [
        "-m", "tools.coverage.report", "--policy", "policy.json", "--config", "coverage.ini",
        "--data-file", ".coverage.runner", "--metadata", "collection.json",
        "--output", "runner.xml", "--artifacts", "artifacts",
    ]
    first = invoke(project, report_command)
    assert first.returncode == 0, first.stdout
    manifest = json.loads((project / "artifacts/manifest.json").read_text())
    assert manifest["files"] == spike[1]["candidate"]["files"]
    assert manifest["totals"] == spike[1]["candidate"]["totals"]
    record = manifest["collection"]
    assert record["pytest_exit"] == 0
    assert record["extension"].startswith("pxiprobe/bridge.")
    assert "pxiprobe/bridge.c" in record["input_hashes"]
    assert (project / "artifacts/coverage-data.sqlite").is_file()
    assert all((project / "artifacts/sources" / p).is_file() for p in record["input_hashes"])
    fresh = invoke(project, report_command)
    assert fresh.returncode == 0, fresh.stdout
    assert json.loads((project / "artifacts/manifest.json").read_text())["files"] == manifest["files"]
    assert report_fixture(project, "--check-fresh").returncode == 0
    assert manifest["accounting"] == {
        "python": {"executable": 1, "covered": 0, "missed": 1},
        "compiled": {"executable": 22, "covered": 4, "missed": 18},
    }

    # The bundle must report independently, even if its old checkout is gone.
    relocated = project.parent / "downloaded"
    shutil.move(project / "artifacts", relocated)
    shutil.rmtree(project)
    replay = invoke(project.parent, [
        "-m", "tools.coverage.report", "--from-artifacts", str(relocated),
        "--output", str(project.parent / "replayed.xml"),
    ])
    assert replay.returncode == 0, replay.stdout
    result = json.loads((project.parent / "replayed.json").read_text())
    assert result["files"] == manifest["files"]
    assert result["accounting"] == manifest["accounting"]
    assert all((relocated / "sources" / p).is_file() for p in result["files"])


def test_declarative_extension_supports_editable_build_and_tracing(runner_project):
    project = runner_project
    for artifact in (project / "pxiprobe").iterdir():
        if artifact.suffix in (".c", ".so", ".pyd"):
            artifact.unlink()
    installed = invoke(project, [
        "-m", "pip", "install", "--no-build-isolation", "--no-deps",
        "--target", str(project.parent / "editable-site"), "-e", ".",
    ])
    assert installed.returncode == 0, installed.stdout
    assert (project / "pxiprobe/bridge.c").is_file()
    assert (project / "pxiprobe/cold.c").is_file()
    collected = run_fixture(project)
    assert collected.returncode == 0, collected.stdout
    data = CoverageData(basename=str(project / ".coverage.runner"))
    data.read()
    assert data.lines(str(project / "pxiprobe/bridge.pyx")) == [6]
    assert set(data.lines(str(project / "pxiprobe/active.pxi"))) == {2, 3, 7}


def test_runner_preserves_pytest_failure_and_report_rejects_it(runner_project, monkeypatch):
    project = runner_project
    with (project / "test_probe.py").open("a") as stream:
        stream.write("\ndef test_failure():\n    assert False\n")
    collected = run_fixture(project)
    assert collected.returncode == 1, collected.stdout
    assert json.loads((project / "collection.json").read_text())["pytest_exit"] == 1
    monkeypatch.chdir(project)
    with pytest.raises(ValueError, match="Successful pytest"):
        validate_collection(project, "policy.json", "coverage.ini", ".coverage.runner", "collection.json")


@pytest.mark.parametrize("source", ["pxiprobe/bridge.c", "pxiprobe/bridge.pyx", "policy.json", "coverage.ini", "binary"])
def test_reporting_rejects_changed_build_or_sources(runner_project, monkeypatch, source):
    project = runner_project
    collected = run_fixture(project)
    assert collected.returncode == 0, collected.stdout
    if source == "binary":
        source = json.loads((project / "collection.json").read_text())["extension"]
    with (project / source).open("a") as stream:
        stream.write("\n")
    monkeypatch.chdir(project)
    with pytest.raises(ValueError, match="changed after collection"):
        validate_collection(project, "policy.json", "coverage.ini", ".coverage.runner", "collection.json")


@pytest.mark.parametrize("kind", ["relative", "duplicate", "external", "unlisted", "wrong-tracer", "python-tracer"])
def test_finalizer_rejects_invalid_data_paths_and_associations(runner_project, kind):
    project = runner_project
    assert run_fixture(project).returncode == 0
    source = str(project / "pxiprobe/bridge.pyx")
    data = CoverageData(basename=str(project / ".coverage.runner"))
    data.read()
    if kind in ("wrong-tracer", "python-tracer"):
        data.erase()
        source = str(project / "pxiprobe/__init__.py") if kind == "python-tracer" else source
        data.add_lines({source: [1]})
        if kind == "python-tracer":
            data.add_file_tracers({source: "Cython.Coverage.Plugin"})
    else:
        source = {
            "relative": "pxiprobe/bridge.pyx",
            "duplicate": str(project / "pxiprobe") + "/../pxiprobe/bridge.pyx",
            "external": str(ROOT / "setup.py"),
            "unlisted": str(project / "test_probe.py"),
        }[kind]
        data.add_lines({source: [1]})
    data.write()
    result = report_fixture(project)
    assert result.returncode != 0, result.stdout
    assert "Unexpected" in result.stdout
    assert not (project / "runner.xml").exists()


def test_source_set_changes_require_an_explicit_policy_update(runner_project, monkeypatch):
    project = runner_project
    monkeypatch.chdir(project)
    policy = json.loads((project / "policy.json").read_text())
    (project / "pxiprobe/inactive.pxi").unlink()
    with pytest.raises(ValueError, match="explained source-set change"):
        discover_inventory(project, "pxiprobe", policy["empty_sources"], policy["executable_sources"])


def test_native_validation_failure_cannot_replace_the_publishable_xml(runner_project, monkeypatch):
    project = runner_project
    assert run_fixture(project).returncode == 0
    assert report_fixture(project).returncode == 0
    xml = (project / "runner.xml").read_bytes()
    monkeypatch.chdir(project)
    inventory = discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])

    def failed_anchor(result):
        raise ValueError("native attribution failed")

    with pytest.raises(ValueError, match="native attribution failed"):
        seed_and_report("coverage.ini", ".coverage.runner", inventory, "runner.xml", project, check=failed_anchor)
    assert (project / "runner.xml").read_bytes() == xml
    assert not (project / "runner.xml.tmp").exists()


def test_fresh_comparison_failure_cannot_replace_the_publishable_xml(runner_project):
    project = runner_project
    assert run_fixture(project).returncode == 0
    assert report_fixture(project).returncode == 0
    xml = (project / "runner.xml").read_bytes()
    summary = json.loads((project / "runner.json").read_text())
    summary["totals"]["covered"] += 1
    (project / "runner.json").write_text(json.dumps(summary))
    result = report_fixture(project, "--check-fresh")
    assert result.returncode != 0 and "Fresh reporting changed" in result.stdout
    assert (project / "runner.xml").read_bytes() == xml


def test_replay_rejects_changed_artifact_inputs(runner_project):
    project = runner_project
    assert run_fixture(project).returncode == 0
    assert report_fixture(project, "--artifacts", "artifacts").returncode == 0
    with (project / "artifacts/sources/pxiprobe/bridge.c").open("a") as stream:
        stream.write("\n")
    result = invoke(project, [
        "-m", "tools.coverage.report", "--from-artifacts", "artifacts", "--output", "replayed.xml",
    ])
    assert result.returncode != 0 and "changed after collection" in result.stdout
    assert not (project / "replayed.xml").exists()


def test_runner_rejects_missing_and_unsupported_policy(runner_project):
    project = runner_project
    policy = project / "policy.json"
    content = json.loads(policy.read_text())
    policy.unlink()
    missing = run_fixture(project)
    assert missing.returncode != 0 and "policy.json" in missing.stdout
    content["mode"] = "whole-source"
    policy.write_text(json.dumps(content))
    unsupported = run_fixture(project)
    assert unsupported.returncode != 0 and "Only the accepted post-bootstrap" in unsupported.stdout


def test_runner_rejects_product_imported_before_its_bootstrap(runner_project):
    result = invoke(runner_project, ["-c", (
        "import pxiprobe; from tools.coverage.run import collect; "
        "collect('policy.json', 'coverage.ini', '.coverage.runner', 'collection.json', ['test_probe.py'])"
    )])
    assert result.returncode != 0 and "before the explicit bootstrap boundary" in result.stdout
