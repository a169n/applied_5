"""Request models. Non-finite numbers are rejected before any maths runs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_SAMPLES = 200_000


class _Strict(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class SimulateRequest(_Strict):
    seed: int = Field(ge=0, le=2**32 - 1)
    x_km: float = Field(ge=-10_000, le=10_000)
    y_km: float = Field(ge=-10_000, le=10_000)
    min_snr: float = Field(gt=0, le=1000)


class PickRequest(_Strict):
    samples: Annotated[list[float], Field(max_length=MAX_SAMPLES)]
    fs_hz: float = Field(gt=0, le=10_000)


class StationPick(_Strict):
    station: str
    t: float


class LocateRequest(_Strict):
    picks: Annotated[list[StationPick], Field(max_length=1000)]
    sigma_s: float | None = Field(default=None, gt=0)
