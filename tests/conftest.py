import pytest
from hypothesis import settings

from quakeloc.calibrate import calibrate

settings.register_profile("ci", derandomize=True, deadline=None, max_examples=30)
settings.load_profile("ci")


@pytest.fixture(scope="session")
def tiny_artifacts(tmp_path_factory):
    """A real calibration with tiny sample sizes, for tests that need a detector."""
    out = tmp_path_factory.mktemp("artifacts")
    calibrate(42, out, n_traces=12, n_noise=12, n_events=3)
    return out
