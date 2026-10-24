"""Run the Phase 2 native macOS build, suite, and source-attribution checks."""

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import sysconfig

from tools.coverage.fidelity_spike import invoke, write_json
from tools.coverage.report import discover_inventory
from tools.coverage.support import environment_metadata, load_policy


def check_layout(snapshot, policy):
    """Test missing-C failure in an artifact copy, never in the measured build."""
    previous = Path.cwd()
    os.chdir(snapshot)
    try:
        inventory = discover_inventory(snapshot, policy["package"], policy["empty_sources"])
        c_file = snapshot / "pyobjus/pyobjus.c"
        saved = c_file.with_suffix(".c.saved")
        c_file.rename(saved)
        try:
            try:
                discover_inventory(snapshot, policy["package"], policy["empty_sources"])
            except FileNotFoundError as error:
                failure = str(error)
            else:
                raise ValueError("Reporting did not reject missing generated C")
        finally:
            saved.rename(c_file)
        restored = discover_inventory(snapshot, policy["package"], policy["empty_sources"])
        if inventory != restored:
            raise ValueError("Restored generated C changed the source inventory")
        return {"missing_c_error": failure, "restoration_identical": True}
    finally:
        os.chdir(previous)


def run_proof(output):
    if sys.platform != "darwin":
        raise ValueError("Native Pyobjus acceptance requires macOS and Apple frameworks")
    environment_metadata()
    root = Path.cwd().resolve()
    policy = load_policy(root / "tools/coverage/policy.json")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    build_environment = {**environment, "PYOBJUS_COVERAGE": "1"}
    compiler = shlex.split(environment.get("CC") or sysconfig.get_config_var("CC"))
    invoke(compiler + ["--version"], root, environment, output / "compiler.log")
    invoke([sys.executable, "-m", "pip", "check"], root, environment, output / "requirements.log")
    invoke([sys.executable, "-m", "pip", "install", "--no-build-isolation", "-e", "."], root, build_environment, output / "install.log")
    invoke([sys.executable, "setup.py", "build_ext", "--inplace", "--force"], root, build_environment, output / "build.log")
    invoke(["make", "test_lib"], root, environment, output / "test-libraries.log")
    invoke([sys.executable, "-m", "pytest", "tools/coverage/tests", "-q"], root, environment, output / "fidelity-tests.log")

    collection = output / "collection.json"
    report = [
        sys.executable, "-m", "tools.coverage.report", "--metadata", str(collection),
        "--output", "coverage.xml", "--artifacts", str(output / "full"),
    ]
    invoke([sys.executable, "-m", "tools.coverage.run", "--metadata", str(collection)], root, environment, output / "pytest.log")
    invoke(report, root, environment, output / "report.log")
    first = json.loads((output / "full/manifest.json").read_text(encoding="utf8"))
    invoke(report, root, environment, output / "fresh-report.log")
    fresh = json.loads((output / "full/manifest.json").read_text(encoding="utf8"))
    if first["files"] != fresh["files"] or first["totals"] != fresh["totals"]:
        raise ValueError("Fresh native reporting changed source accounting")

    control_data = output / ".coverage.literals"
    control_metadata = output / "literals-collection.json"
    invoke([
        sys.executable, "-m", "tools.coverage.run", "--data-file", str(control_data),
        "--metadata", str(control_metadata), "--", "tests/test_literals.py", "-v",
    ], root, environment, output / "literals-pytest.log")
    invoke([
        sys.executable, "-m", "tools.coverage.report", "--data-file", str(control_data),
        "--metadata", str(control_metadata), "--native-checks", "literals",
        "--output", str(output / "literals.xml"), "--artifacts", str(output / "literals"),
    ], root, environment, output / "literals-report.log")
    result = {
        "status": "passed", "native_gate_approval": "pending", "policy": policy,
        "totals": first["totals"], "native_anchors": first["native_anchors"],
        "layout_check": check_layout(output / "full/sources", policy),
        "fresh_accounting_identical": True,
        "uncalled_control": "literals-only selection does not call the public dereference function",
    }
    write_json(output / "acceptance.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/coverage-native"))
    args = parser.parse_args()
    print(json.dumps(run_proof(args.output), indent=2))


if __name__ == "__main__":
    main()
