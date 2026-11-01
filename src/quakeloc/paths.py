"""Filesystem locations, overridable through the environment."""

import os
from pathlib import Path


def config_dir() -> Path:
    return Path(os.environ.get("QUAKELOC_CONFIG", "config"))


def artifacts_dir() -> Path:
    return Path(os.environ.get("QUAKELOC_ARTIFACTS", "artifacts"))


def snapshot_dir() -> Path:
    return Path(os.environ.get("QUAKELOC_SNAPSHOT", "data/real"))
