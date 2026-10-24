from pathlib import Path
import runpy
import shutil
import sys

from Cython.Distutils import build_ext
import pytest
from setuptools import Distribution
from setuptools.errors import PlatformError
import setuptools


ROOT = Path(__file__).resolve().parents[3]


def build_command(tmp_path, monkeypatch):
    shutil.copyfile(ROOT / "setup.py", tmp_path / "setup.py")
    (tmp_path / "pyobjus").mkdir()
    (tmp_path / "pyobjus/__init__.py").write_text("__version__ = '0.0.0'\n")
    monkeypatch.chdir(tmp_path)
    setup_args = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: setup_args.update(kwargs))
    runpy.run_path(str(tmp_path / "setup.py"))
    command = setup_args["cmdclass"]["build_ext"](Distribution({"ext_modules": setup_args["ext_modules"]}))
    command.ensure_finalized()
    # Keep platform/configuration checks without attempting a native build.
    monkeypatch.setattr(build_ext, "build_extensions", lambda self: None)
    return command


@pytest.mark.parametrize("value", [None, "0", "1"])
def test_coverage_controls_are_explicitly_opt_in(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("PYOBJUS_COVERAGE", raising=False)
    else:
        monkeypatch.setenv("PYOBJUS_COVERAGE", value)
    command = build_command(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")
    command.build_extensions()
    extension = command.extensions[0]
    macros = dict(extension.define_macros)
    if value == "1":
        assert extension.cython_directives["linetrace"] is True
        assert extension.cython_directives["emit_code_comments"] is True
        assert macros["CYTHON_TRACE"] == "1" and macros["CYTHON_USE_SYS_MONITORING"] == "0"
    else:
        assert "linetrace" not in extension.cython_directives
        assert "CYTHON_TRACE" not in macros and "CYTHON_USE_SYS_MONITORING" not in macros
    # Native proof commands explicitly request --force; the build hook does not.
    assert not command.force
    assert (tmp_path / "pyobjus/config.pxi").read_text().startswith('DEF PLATFORM = "darwin"\n')


def test_coverage_does_not_bypass_unsupported_platform_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("PYOBJUS_COVERAGE", "1")
    command = build_command(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(PlatformError, match="can only be built on macOS or iOS"):
        command.build_extensions()
    assert not (tmp_path / "pyobjus/config.pxi").exists()
