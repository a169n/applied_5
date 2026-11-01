import pytest

from quakeloc.stats import chi2_2_quantile, f_2_nu_quantile


def test_chi2_2_95():
    assert chi2_2_quantile(0.95) == pytest.approx(5.991, abs=1e-3)


def test_f_2_5_95():
    assert f_2_nu_quantile(0.95, 5) == pytest.approx(5.786, abs=1e-3)


def test_f_2_large_nu_approaches_chi2_over_2():
    assert f_2_nu_quantile(0.95, 100000) == pytest.approx(5.991 / 2, abs=1e-3)
