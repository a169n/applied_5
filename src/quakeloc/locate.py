"""Epicentre location: Geiger's method as damped Gauss-Newton (Levenberg-Marquardt)."""

import math
from dataclasses import dataclass

import numpy as np

from quakeloc.model import DEPTH_KM, VP_KM_S, travel_time
from quakeloc.stats import chi2_2_quantile, f_2_nu_quantile

_MAX_ITER = 50
_STEP_TOL = 1e-6
_UNDAMPED_TOL = 1e-3
_MAX_DAMPING = 1e6
_MIN_APERTURE_RATIO = 0.05
_CONFIDENCE = 0.95


class LocationError(ValueError):
    """No trustworthy location exists for this input."""


@dataclass(frozen=True)
class Ellipse:
    a_km: float
    b_km: float
    azimuth_deg: float  # of the major axis, clockwise from north, in [0, 180)

    def contains(self, dx_km, dy_km) -> bool:
        """Whether an offset (east, north) from the centre lies inside the ellipse."""
        if self.b_km <= 0:
            return False
        az = math.radians(self.azimuth_deg)
        along = dx_km * math.sin(az) + dy_km * math.cos(az)
        across = dx_km * math.cos(az) - dy_km * math.sin(az)
        return (along / self.a_km) ** 2 + (across / self.b_km) ** 2 <= 1.0


@dataclass(frozen=True)
class Solution:
    x_km: float
    y_km: float
    t0: float
    rms_s: float
    iterations: int
    cond: float
    ellipse: Ellipse


def _jacobian(x, y, sta_xy, h_km) -> np.ndarray:
    """Partial derivatives of the arrival time with respect to (x, y, t0)."""
    dx, dy = x - sta_xy[:, 0], y - sta_xy[:, 1]
    r = np.sqrt(dx**2 + dy**2 + (DEPTH_KM + h_km) ** 2)
    return np.column_stack([-dx / (VP_KM_S * r), dy / (VP_KM_S * r), np.ones(len(r))])


def _ellipse(g, residuals, sigma_s) -> Ellipse:
    gtg = g.T @ g
    if np.linalg.matrix_rank(g) < 3:
        raise LocationError("singular geometry: the Jacobian is rank deficient")
    if sigma_s is not None:
        s2, k2 = sigma_s**2, chi2_2_quantile(_CONFIDENCE)
    else:
        nu = len(residuals) - 3
        s2, k2 = np.sum(residuals**2) / nu, 2 * f_2_nu_quantile(_CONFIDENCE, nu)
    values, vectors = np.linalg.eigh(s2 * np.linalg.inv(gtg)[:2, :2])
    major = vectors[:, 1]
    azimuth = math.degrees(math.atan2(major[0], major[1])) % 180.0
    a, b = np.sqrt(k2 * np.clip(values[::-1], 0.0, None))
    return Ellipse(float(a), float(b), azimuth)


def locate(sta_xy, h_km, t_obs, sigma_s=None, jacobian=_jacobian) -> Solution:
    sta_xy, h_km, t_obs = (np.asarray(a, dtype=float) for a in (sta_xy, h_km, t_obs))
    n = len(t_obs)
    if n < 4:
        raise LocationError(f"need at least 4 picks, got {n}")
    if not np.all(np.isfinite(t_obs)):
        raise LocationError("pick times must be finite")
    if sigma_s is not None and not sigma_s > 0:
        raise LocationError("sigma_s must be positive")
    aperture = np.linalg.svd(sta_xy - sta_xy.mean(axis=0), compute_uv=False)
    if aperture[-1] < _MIN_APERTURE_RATIO * aperture[0]:
        raise LocationError("stations are nearly collinear")

    first = int(np.argmin(t_obs))
    x, y = sta_xy[first]
    t0 = t_obs[first] - travel_time(x, y, sta_xy, h_km)[first]

    def residuals(x, y, t0):
        return t_obs - (t0 + travel_time(x, y, sta_xy, h_km))

    r = residuals(x, y, t0)
    damping = 1e-3
    iterations = 0
    for iterations in range(1, _MAX_ITER + 1):  # noqa: B007 (reported after the loop)
        g = jacobian(x, y, sta_xy, h_km)
        scale = np.sqrt(damping) * np.linalg.norm(g, axis=0)
        augmented = np.vstack([g, np.diag(scale)])
        rhs = np.concatenate([r, np.zeros(3)])
        step = np.linalg.lstsq(augmented, rhs, rcond=None)[0]
        if np.linalg.norm(step) < _STEP_TOL:
            break
        candidate = residuals(x + step[0], y + step[1], t0 + step[2])
        if candidate @ candidate < r @ r:
            x, y, t0, r = x + step[0], y + step[1], t0 + step[2], candidate
            damping /= 10
        else:
            damping *= 10

    g = jacobian(x, y, sta_xy, h_km)
    undamped = np.linalg.lstsq(g, r, rcond=None)[0]
    if np.linalg.norm(undamped) >= _UNDAMPED_TOL or damping >= _MAX_DAMPING:
        raise LocationError("location stalled: the solver did not reach a stationary point")
    return Solution(
        x_km=float(x),
        y_km=float(y),
        t0=float(t0),
        rms_s=float(np.sqrt(np.mean(r**2))),
        iterations=iterations,
        cond=float(np.linalg.cond(g)),
        ellipse=_ellipse(g, r, sigma_s),
    )
