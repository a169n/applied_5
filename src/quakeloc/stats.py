"""Closed-form quantiles for 2-D confidence ellipses (no scipy needed)."""

import math


def chi2_2_quantile(p: float) -> float:
    return -2.0 * math.log(1.0 - p)


def f_2_nu_quantile(p: float, nu: int) -> float:
    return (nu / 2.0) * ((1.0 - p) ** (-2.0 / nu) - 1.0)
