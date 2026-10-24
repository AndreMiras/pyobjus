"""Shared policy and collection provenance for coverage developer commands."""

import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys


PINS = {"Cython": "3.3.0", "coverage": "7.17.0", "pytest-cov": "7.1.0", "pytest": "9.1.1"}


def load_policy(path):
    policy = json.loads(Path(path).read_text(encoding="utf8"))
    required = {
        "mode", "package", "bootstrap", "extension", "empty_sources", "executable_sources", "label",
        "numerator", "compiled_denominator", "initialization_only_lines",
    }
    if not isinstance(policy, dict) or not required.issubset(policy):
        raise ValueError("Coverage policy is incomplete")
    if policy["mode"] != "post-bootstrap":
        raise ValueError("Only the accepted post-bootstrap coverage policy is supported")
    package = policy["package"]
    if not isinstance(package, str) or not package.isidentifier():
        raise ValueError("Coverage policy must name a top-level product package")
    if policy["bootstrap"] != [package] or not policy["extension"].startswith(package + "."):
        raise ValueError("Coverage bootstrap and extension must belong to the product package")
    declarations = []
    for key in ("empty_sources", "executable_sources"):
        sources = policy[key]
        if not isinstance(sources, list) or any(
            not isinstance(p, str) or Path(p).parts[:1] != (package,)
            or ".." in Path(p).parts or Path(p).suffix not in (".pyx", ".pxi")
            for p in sources
        ):
            raise ValueError("Source declarations must belong to the product package")
        declarations.extend(sources)
    if not policy["executable_sources"] or len(set(declarations)) != len(declarations):
        raise ValueError("Source declarations must be nonoverlapping and include executable sources")
    return policy


def environment_metadata():
    versions = {name: metadata.version(name) for name in PINS}
    if sys.version_info[:2] != (3, 14) or versions != PINS:
        raise ValueError("Use Python 3.14 and install .ci/coverage-requirements.txt")
    return {
        "python": sys.version, "platform": platform.platform(),
        "architecture": platform.machine(), "versions": versions,
        "build_versions": {name: metadata.version(name) for name in ("setuptools", "wheel")},
        "packages": sorted(
            ({"name": d.metadata["Name"], "version": d.version} for d in metadata.distributions()),
            key=lambda d: d["name"].lower(),
        ),
    }


def input_hashes(root, package, config, policy, extension):
    root = Path(root).resolve()
    paths = {
        p.resolve() for p in (root / package).rglob("*")
        if p.is_file() and p.suffix in (".py", ".pyx", ".pxi", ".h", ".c")
    }
    paths.update(Path(p).resolve() for p in (config, policy, extension))
    for name in (
        "setup.py", "pyproject.toml", ".ci/coverage-requirements.txt", ".ci/cicd-requirements.txt",
        "tools/coverage/__init__.py", "tools/coverage/run.py", "tools/coverage/report.py",
        "tools/coverage/support.py",
    ):
        if (root / name).is_file():
            paths.add(root / name)
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }
