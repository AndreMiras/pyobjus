import json
from pathlib import Path
import runpy
import shutil

from Cython.Build import cythonize
from setuptools import Extension

from tools.coverage.report import discover_inventory


ROOT = Path(__file__).resolve().parents[3]


def test_current_product_generates_macos_source_inventory(tmp_path, monkeypatch):
    """Source generation/reporting check; does not compile or execute Apple APIs."""
    package = tmp_path / "pyobjus"
    package.mkdir()
    for source in (ROOT / "pyobjus").iterdir():
        if source.suffix in (".pyx", ".pxi", ".h") or source.name == "__init__.py":
            shutil.copyfile(source, package / source.name)
    (package / "config.pxi").write_text('DEF PLATFORM = "darwin"\nDEF ARCH = "arm64"\n')
    monkeypatch.chdir(tmp_path)
    cythonize(
        [Extension("pyobjus.pyobjus", ["pyobjus/pyobjus.pyx"])],
        compiler_directives={"linetrace": True, "emit_code_comments": True},
        force=True, quiet=True,
    )
    policy = json.loads((ROOT / "tools/coverage/policy.json").read_text())
    inventory = discover_inventory(tmp_path, "pyobjus", policy["empty_sources"])
    compact = runpy.run_path(str(ROOT / ".ci/cython_coverage_proof.py"))
    assert compact["inventory"]("pyobjus", {"common.pxi", "config.pxi"}) == inventory
    nonempty = {Path(source).name for source, lines in inventory.items() if lines}
    assert nonempty == {
        "pyobjus.pyx", "pyobjus_types.pxi", "pyobjus_conversions.pxi", "type_enc.pxi", "debug.pxi",
    }
    assert all(not inventory[str(tmp_path / source)] for source in policy["empty_sources"])
    body = (package / "pyobjus_conversions.pxi").read_text().splitlines().index("    if py_ptr is None:") + 1
    assert body in inventory[str(package / "pyobjus_conversions.pxi")]
