"""Measure pytest after the accepted package bootstrap, retaining provenance."""

import argparse
import importlib
from importlib.machinery import EXTENSION_SUFFIXES
import json
import os
from pathlib import Path
import sys
import time

from coverage import Coverage

from tools.coverage.report import discover_inventory
from tools.coverage.support import environment_metadata, input_hashes, load_policy


def collect(policy_file, config_file, data_file, metadata_file, pytest_args):
    import pytest

    root = Path.cwd().resolve()
    policy_file = Path(policy_file).resolve()
    config_file = Path(config_file).resolve()
    data_file = Path(data_file).resolve()
    metadata_file = Path(metadata_file).resolve()
    policy = load_policy(policy_file)
    environment = environment_metadata()
    package = policy["package"]
    if any(name == package or name.startswith(package + ".") for name in sys.modules):
        raise ValueError("Product was imported before the explicit bootstrap boundary")
    if os.environ.get("COVERAGE_CORE", "ctrace") != "ctrace" or os.environ.get("COVERAGE_PROCESS_START"):
        raise ValueError("Remove automatic/overridden coverage collection from the environment")
    if any(arg.startswith("--cov") for arg in pytest_args):
        raise ValueError("The runner owns coverage collection; do not pass pytest-cov options")
    discover_inventory(root, package, policy["empty_sources"], policy["executable_sources"])
    cov = Coverage(config_file=str(config_file), data_file=str(data_file))
    if (cov.get_option("run:core") != "ctrace" or cov.get_option("run:branch")
            or cov.get_option("run:source") != [package]
            or cov.get_option("run:plugins") != ["Cython.Coverage"]):
        raise ValueError("Coverage must use Cython.Coverage, ctrace, and line mode")
    # All product initialization, including transitive imports, is excluded.
    sys.path.insert(0, str(root))
    importlib.import_module(package)
    extension = sys.modules.get(policy["extension"])
    binary = Path(getattr(extension, "__file__", "")).resolve()
    if not binary.is_relative_to(root / package) or not str(binary).endswith(tuple(EXTENSION_SUFFIXES)):
        raise ValueError("Bootstrap did not load the compiled extension from this checkout")
    hashes = input_hashes(root, package, config_file, policy_file, binary)
    record = {
        **environment, "project_root": str(root), "policy": policy,
        "policy_file": str(policy_file.relative_to(root)),
        "config_file": str(config_file.relative_to(root)),
        "data_file": str(data_file), "extension": str(binary.relative_to(root)),
        "input_hashes": hashes, "pytest_args": pytest_args,
        "measurement_start": "after package bootstrap, before pytest.main()",
        "pytest_exit": None,
    }
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    cov.start()
    try:
        status = pytest.main(["-p", "no:pytest_cov", *pytest_args])
        record["pytest_exit"] = int(status)
    finally:
        cov.stop()
        cov.save()
        record["duration_seconds"] = time.monotonic() - start
        metadata_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    return int(status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="tools/coverage/policy.json")
    parser.add_argument("--config", default="tools/coverage/coverage.toml")
    parser.add_argument("--data-file", default=".coverage")
    parser.add_argument("--metadata", default="build/coverage-run.json")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    raise SystemExit(collect(
        args.policy, args.config, args.data_file, args.metadata,
        pytest_args or ["tests", "-v"],
    ))


if __name__ == "__main__":
    main()
