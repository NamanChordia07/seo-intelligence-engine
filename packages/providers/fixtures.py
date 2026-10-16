"""Fixture loading (cached). All fixture data is SIMULATED unless stated otherwise."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from packages.config import FIXTURES_DIR


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def project_fixture() -> dict[str, Any]:
    return _load(FIXTURES_DIR / "project.yaml")


@lru_cache
def days_fixture() -> dict[str, Any]:
    return _load(FIXTURES_DIR / "days.yaml")


@lru_cache
def serps_fixture() -> dict[str, Any]:
    return _load(FIXTURES_DIR / "serps.yaml")


@lru_cache
def evidence_fixture() -> list[dict[str, Any]]:
    return _load(FIXTURES_DIR / "evidence.yaml")


@lru_cache
def inventory_fixture() -> list[dict[str, Any]]:
    return _load(FIXTURES_DIR / "inventory.yaml")


@lru_cache
def content_library() -> dict[str, dict[str, Any]]:
    lib: dict[str, dict[str, Any]] = {}
    for p in sorted((FIXTURES_DIR / "content").glob("*.yaml")):
        doc = _load(p)
        lib[doc["intent_key"]] = doc
    return lib


def day_config(sim_day: int) -> dict[str, Any]:
    days = days_fixture()
    key = f"day{sim_day}"
    if key not in days:
        raise KeyError(f"No fixture for simulated day {sim_day}")
    return days[key]


def available_days() -> list[int]:
    return sorted(int(k.removeprefix("day")) for k in days_fixture())
