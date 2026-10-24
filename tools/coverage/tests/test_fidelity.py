import json
import shutil
import xml.etree.ElementTree as ET

from coverage import CoverageData
import pytest

from tools.coverage.report import discover_inventory, seed_and_report, xml_accounting


def test_import_alias_and_candidate_body_attribution(spike):
    _, result = spike
    raw = result["raw"]["files"]
    candidate = result["candidate"]["files"]
    assert 9 in raw["pxiprobe/bridge.pyx"]["hits"]
    assert 9 in candidate["pxiprobe/bridge.pyx"]["misses"]
    assert 10 in candidate["pxiprobe/active.pxi"]["misses"]
    assert 4 in candidate["pxiprobe/active.pxi"]["misses"]
    assert {2, 3, 7} <= set(candidate["pxiprobe/active.pxi"]["hits"])
    assert 6 in candidate["pxiprobe/bridge.pyx"]["hits"]
    assert any(e["function"] == "PyInit_bridge" and e["line"] == 9 for e in result["trace_events"]["import"])


@pytest.mark.parametrize("name", ["inactive.pxi", "cold.pyx", "cold_impl.pxi"])
def test_wholly_unexecuted_sources_are_missed(spike, name):
    _, result = spike
    source = f"pxiprobe/{name}"
    assert source not in result["raw_unseeded"]
    assert source not in result["candidate_unseeded"]
    for mode in ("raw", "candidate"):
        assert result[mode]["files"][source] == {
            "hits": [], "misses": result[mode]["inventory"][source],
        }


def test_denominator_is_retained_including_excluded_initialization(spike):
    _, result = spike
    assert result["raw"]["inventory"] == result["candidate"]["inventory"]
    assert result["raw"]["totals"]["executable"] == result["candidate"]["totals"]["executable"]
    assert result["candidate"]["inventory"]["pxiprobe/declarations.pxi"] == []
    assert "pxiprobe/declarations.pxi" not in result["candidate"]["files"]
    assert result["raw"]["files"]["pxiprobe/__init__.py"]["hits"] == [1]
    assert result["candidate"]["files"]["pxiprobe/__init__.py"]["misses"] == [1]


def test_seeding_preserves_hits_and_fresh_process_is_idempotent(spike):
    _, result = spike
    for mode in ("raw", "candidate"):
        report = result[mode]
        for name, lines in report["measured_before"].items():
            assert report["measured_after"][name] == lines
    assert result["candidate"]["files"] == result["fresh"]["files"]
    assert result["candidate"]["measured_after"] == result["fresh"]["measured_before"] == result["fresh"]["measured_after"]


def test_xml_resolves_to_the_built_fixture_copy(spike):
    output, result = spike
    project = output / "project"
    assert xml_accounting(project / "post-bootstrap-seeded.xml", project) == result["candidate"]["files"]
    assert all((project / name).is_file() for name in result["candidate"]["files"])
    assert set(result["candidate"]["files"]) == {
        "pxiprobe/__init__.py", "pxiprobe/bridge.pyx", "pxiprobe/active.pxi",
        "pxiprobe/inactive.pxi", "pxiprobe/cold.pyx", "pxiprobe/cold_impl.pxi",
    }


def test_explicit_empty_dataset_counts_all_inventory_lines_as_missed(spike, monkeypatch, tmp_path):
    output, _ = spike
    project = output / "project"
    monkeypatch.chdir(project)
    inventory = discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])
    data_file = tmp_path / "empty.data"
    data = CoverageData(basename=str(data_file))
    data.add_lines({})
    data.write()
    result = seed_and_report("coverage.ini", data_file, inventory, tmp_path / "empty.xml", project)
    assert result["totals"]["covered"] == 0
    for source, lines in result["inventory"].items():
        if lines:
            assert result["files"][source] == {"hits": [], "misses": lines}


def test_missing_collection_data_cannot_create_a_zero_baseline(spike, monkeypatch, tmp_path):
    output, _ = spike
    project = output / "project"
    monkeypatch.chdir(project)
    inventory = discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])
    xml = tmp_path / "missing.xml"
    with pytest.raises(FileNotFoundError, match="Collected coverage data"):
        seed_and_report("coverage.ini", tmp_path / "missing.data", inventory, xml, project)
    assert not xml.exists()


def test_missing_generated_c_fails_in_disposable_copy(spike, monkeypatch, tmp_path):
    output, _ = spike
    project = tmp_path / "copy"
    shutil.copytree(output / "project", project)
    monkeypatch.chdir(project)
    original = discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])
    c_file = project / "pxiprobe/bridge.c"
    saved = c_file.read_bytes()
    c_file.unlink()
    with pytest.raises(FileNotFoundError, match="Matching generated C"):
        discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])
    c_file.write_bytes(saved)
    assert discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"]) == original


def test_discovery_failure_is_distinct_from_declared_empty(spike, monkeypatch, tmp_path):
    output, _ = spike
    project = tmp_path / "copy"
    shutil.copytree(output / "project", project)
    monkeypatch.chdir(project)
    (project / "pxiprobe/orphan.pxi").write_text("def omitted():\n    return 1\n")
    with pytest.raises(ValueError, match="Missing executable source mapping.*orphan"):
        discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])


def test_source_hashes_and_versions_are_retained(spike):
    output, _ = spike
    environment = json.loads((output / "environment.json").read_text())
    assert environment["versions"] == {"Cython": "3.3.0", "coverage": "7.17.0", "pytest-cov": "7.1.0", "pytest": "9.1.1"}
    assert environment["compiler_version"]
    hashes = json.loads((output / "source-hashes.json").read_text())
    assert "pxiprobe/bridge.pyx" in hashes
    assert all(len(digest) == 64 for digest in hashes.values())


@pytest.mark.parametrize("corruption", ["duplicate-source", "duplicate-line", "outside-root", "ambiguous", "totals"])
def test_xml_path_and_accounting_corruption_is_rejected(spike, tmp_path, corruption):
    output, _ = spike
    project = tmp_path / "project"
    shutil.copytree(output / "project", project)
    xml = ET.parse(project / "post-bootstrap-seeded.xml")
    root = xml.getroot()
    root.find("./sources/source").text = str(project / "pxiprobe")
    classes = root.find("./packages/package/classes")
    if corruption == "duplicate-source":
        classes.append(ET.fromstring(ET.tostring(classes[0])))
    elif corruption == "duplicate-line":
        lines = classes[0].find("lines")
        lines.append(ET.fromstring(ET.tostring(lines[0])))
    elif corruption == "outside-root":
        classes[0].set("filename", str(tmp_path / "external.py"))
        (tmp_path / "external.py").write_text("pass\n")
    elif corruption == "ambiguous":
        alternative = project / "alternative"
        alternative.mkdir(exist_ok=True)
        shutil.copyfile(project / "pxiprobe/__init__.py", alternative / "__init__.py")
        ET.SubElement(root.find("sources"), "source").text = str(alternative)
    else:
        root.set("lines-valid", "1")
    path = tmp_path / "invalid.xml"
    xml.write(path)
    with pytest.raises(ValueError):
        xml_accounting(path, project)


def test_adapter_rejects_an_executable_original_outside_the_package(spike, tmp_path, monkeypatch):
    project = tmp_path / "copy"
    shutil.copytree(spike[0] / "project", project)
    monkeypatch.chdir(project)
    (project / "unexpected.pxi").write_text("return 1\n")
    with (project / "pxiprobe/bridge.c").open("a") as stream:
        stream.write('/* "unexpected.pxi":1\n * return 1 # <<<<<<<<<<<<<<\n */\n __Pyx_TraceLine(1,0,0,0)\n')
    with pytest.raises(ValueError, match="Unexpected executable original-source mapping"):
        discover_inventory(project, "pxiprobe", ["pxiprobe/declarations.pxi"])
