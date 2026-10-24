"""Build an isolated Cython fixture and compare raw vs post-bootstrap coverage."""

import argparse
import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import sysconfig

from tools.coverage.report import measured_hits, xml_accounting


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "tests" / "fixture"
PINS = {"Cython": "3.3.0", "coverage": "7.17.0", "pytest-cov": "7.1.0", "pytest": "9.1.1"}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")


def invoke(command, project, environment, log):
    result = subprocess.run(
        command, cwd=project, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    log.write_text(result.stdout, encoding="utf8")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {shlex.join(command)}\n{result.stdout}")
    return result.stdout


def file_hashes(directory, paths):
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def collect(mode):
    """Worker: a fresh interpreter for each collection interval."""
    import pytest
    from coverage import Coverage

    sys.path.insert(0, str(Path.cwd()))
    if any(name == "pxiprobe" or name.startswith("pxiprobe.") for name in sys.modules):
        raise RuntimeError("Fixture was imported before the explicit bootstrap boundary")
    if mode == "post-bootstrap":
        importlib.import_module("pxiprobe")
    cov = Coverage(config_file="coverage.ini", data_file=f".coverage.{mode}")
    cov.start()
    try:
        status = pytest.main(["-p", "no:pytest_cov", "test_probe.py", "-q"])
    finally:
        cov.stop()
        cov.save()
    if status:
        raise SystemExit(status)
    if "pxiprobe.cold" in sys.modules:
        raise RuntimeError("The cold-extension control was imported")
    cov.xml_report(outfile=f"{mode}-unseeded.xml")
    write_json(Path(f"{mode}-collection.json"), {
        "mode": mode,
        "pytest_exit": int(status),
        "measured": measured_hits(cov.get_data()),
        "files": xml_accounting(f"{mode}-unseeded.xml", Path.cwd()),
        "extension": sys.modules["pxiprobe.bridge"].__file__,
    })


def trace_events():
    """Worker: record original events independently of coverage.py."""
    sys.path.insert(0, str(Path.cwd()))
    events = {"import": [], "call": []}
    phase = "import"

    def tracer(frame, event, arg):
        source = frame.f_code.co_filename
        if event == "line" and source.endswith((".pyx", ".pxi")):
            events[phase].append({
                "source": source, "line": frame.f_lineno,
                "function": frame.f_code.co_name,
            })
        return tracer

    sys.settrace(tracer)
    try:
        package = importlib.import_module("pxiprobe")
        phase = "call"
        if package.compute(2) != 12:
            raise RuntimeError("Unexpected fixture result")
    finally:
        sys.settrace(None)
    write_json(Path("trace-events.json"), events)


def verify_comparison(raw, candidate, unseeded, fresh, events):
    """Fail the command if any design-gate invariant is not demonstrated."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    main = "pxiprobe/bridge.pyx"
    active = "pxiprobe/active.pxi"
    require(9 in raw["files"][main]["hits"], "Raw initialization false hit was not reproduced")
    require(9 in candidate["files"][main]["misses"], "Uncalled main body received a hit")
    require(10 in candidate["files"][active]["misses"], "Uncalled include body received a hit")
    require(4 in candidate["files"][active]["misses"], "Untaken branch received a hit")
    require({2, 3, 7}.issubset(candidate["files"][active]["hits"]), "Missing include def/cdef body hits")
    require(6 in candidate["files"][main]["hits"], "Missing main-source call body hit")
    for name in ("inactive.pxi", "cold.pyx", "cold_impl.pxi"):
        source = f"pxiprobe/{name}"
        require(source not in unseeded, f"Cold-source control unexpectedly represented: {source}")
        for result in (raw, candidate):
            require(not result["files"][source]["hits"], f"Cold source received hits: {source}")
            require(result["files"][source]["misses"] == result["inventory"][source], f"Cold inventory omitted: {source}")
    empty = "pxiprobe/declarations.pxi"
    require(candidate["inventory"][empty] == [], "Declaration-only inventory is not empty")
    require(empty not in candidate["files"], "Declaration-only source invented a denominator")
    require(raw["inventory"] == candidate["inventory"], "Candidate changed the source inventory")
    require(raw["totals"]["executable"] == candidate["totals"]["executable"], "Candidate changed the total denominator")
    require(candidate["files"] == fresh["files"], "Fresh report changed accounting")
    require(candidate["measured_after"] == fresh["measured_before"] == fresh["measured_after"], "Repeated seeding changed hits")
    require(1 in raw["files"]["pxiprobe/__init__.py"]["hits"], "Raw Python import control missing")
    require(1 in candidate["files"]["pxiprobe/__init__.py"]["misses"], "Excluded Python bootstrap received a hit")
    require(any(
        event["source"].endswith("bridge.pyx") and event["line"] == 9
        and event["function"] == "PyInit_bridge" for event in events["import"]
    ), "Independent trace did not identify the import-time alias")
    require(any(event["source"].endswith("active.pxi") and event["line"] == 3 for event in events["call"]), "Independent include body event missing")


def run_spike(output):
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("The Phase 1 fidelity spike requires Python 3.14")
    versions = {name: metadata.version(name) for name in PINS}
    if versions != PINS:
        raise RuntimeError(f"Install .ci/coverage-requirements.txt; found {versions}")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / "project"
    shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", "build", "*.pyc", "*.c", "*.so", "*.pyd",
    ))
    sources = [p for p in project.rglob("*") if p.is_file()]
    before = file_hashes(project, sources)
    environment = os.environ.copy()
    for name in ("COVERAGE_FILE", "COVERAGE_PROCESS_START", "COVERAGE_CORE", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    environment.update(
        PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
    )
    environment.setdefault("CFLAGS", "-O0")
    compiler = shlex.split(environment.get("CC") or sysconfig.get_config_var("CC"))
    compiler_version = invoke(compiler + ["--version"], project, environment, output / "compiler.log")
    write_json(output / "environment.json", {
        "python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "architecture": platform.machine(),
        "versions": versions, "compiler": compiler, "compiler_version": compiler_version,
        "compiler_environment": {name: environment.get(name) for name in ("CC", "CXX", "LDSHARED", "CFLAGS", "LDFLAGS")},
        "packages": sorted(
            ({"name": d.metadata["Name"], "version": d.version} for d in metadata.distributions()),
            key=lambda d: d["name"].lower(),
        ),
        "directives": {"linetrace": True, "emit_code_comments": True},
        "define_macros": {"CYTHON_TRACE": "1", "CYTHON_USE_SYS_MONITORING": "0"},
        "coverage_core": "ctrace", "coverage_plugin": "Cython.Coverage",
    })
    write_json(output / "source-hashes.json", before)
    invoke([sys.executable, "setup.py", "build_ext", "--inplace", "--force"], project, environment, output / "build.log")
    if file_hashes(project, sources) != before:
        raise RuntimeError("The build changed original fixture source bytes")
    write_json(output / "build-hashes.json", file_hashes(project, [
        p for p in (project / "pxiprobe").iterdir() if p.suffix in (".c", ".so", ".pyd")
    ]))
    prefix = [sys.executable, "-m", "tools.coverage.fidelity_spike"]
    for mode in ("raw", "post-bootstrap"):
        invoke(prefix + ["--worker", "collect", "--mode", mode], project, environment, output / f"{mode}-pytest.log")
        shutil.copyfile(project / f".coverage.{mode}", project / f".coverage.{mode}-seeded")
        invoke([
            sys.executable, "-m", "tools.coverage.report", "--package", "pxiprobe",
            "--data-file", f".coverage.{mode}-seeded", "--empty-source", "pxiprobe/declarations.pxi",
            "--output", f"{mode}-seeded.xml",
        ], project, environment, output / f"{mode}-report.log")
    invoke([
        sys.executable, "-m", "tools.coverage.report", "--package", "pxiprobe",
        "--data-file", ".coverage.post-bootstrap-seeded", "--empty-source", "pxiprobe/declarations.pxi",
        "--output", "post-bootstrap-fresh.xml",
    ], project, environment, output / "fresh-report.log")
    invoke(prefix + ["--worker", "trace"], project, environment, output / "trace.log")

    def load(name):
        return json.loads((project / name).read_text(encoding="utf8"))

    raw = load("raw-seeded.json")
    candidate = load("post-bootstrap-seeded.json")
    fresh = load("post-bootstrap-fresh.json")
    events = load("trace-events.json")
    verify_comparison(raw, candidate, load("raw-collection.json")["files"], fresh, events)
    result = {
        "status": "passed", "policy_approval": "pending",
        "proposed_mode": "post-bootstrap", "raw": raw, "candidate": candidate,
        "fresh": fresh, "trace_events": events,
        "raw_unseeded": load("raw-collection.json")["files"],
        "candidate_unseeded": load("post-bootstrap-collection.json")["files"],
    }
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("collect", "trace"), help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("raw", "post-bootstrap"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker == "collect":
        if args.mode is None:
            parser.error("collection worker requires --mode")
        collect(args.mode)
    elif args.worker == "trace":
        trace_events()
    else:
        if args.output is None:
            parser.error("--output is required (choose a new directory for each run)")
        result = run_spike(args.output)
        print(json.dumps({"raw": result["raw"]["totals"], "post-bootstrap": result["candidate"]["totals"], "policy_approval": "pending"}, indent=2))


if __name__ == "__main__":
    main()
