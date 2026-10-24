from pathlib import Path

import pytest

from tools.coverage.fidelity_spike import run_spike


# This package must be compiled/copied before its test is collected.
collect_ignore = ["fixture"]


@pytest.fixture(scope="session")
def spike(tmp_path_factory):
    directory = tmp_path_factory.mktemp("coverage-fidelity") / "run"
    result = run_spike(directory)
    return Path(directory), result
