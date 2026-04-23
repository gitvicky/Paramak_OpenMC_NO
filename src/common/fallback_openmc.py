from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np


FALLBACK_STATEPOINT_FORMAT = "macos_fallback_statepoint_v1"


def _mesh_size(mesh_cfg: dict) -> int:
    size = 1
    for value in mesh_cfg["dimension"]:
        size *= int(value)
    return size


def _build_series(*, start: float, step: float, count: int, scale: float) -> list[float]:
    indices = np.arange(count, dtype=float)
    return (start + (indices * step * scale)).tolist()


def build_fallback_statepoint_payload(iteration_id: int, mesh_cfg: dict) -> dict:
    mesh_size = _mesh_size(mesh_cfg)
    scale = 1.0 + (float(iteration_id) * 0.01)

    return {
        "format": FALLBACK_STATEPOINT_FORMAT,
        "iteration_id": int(iteration_id),
        "tallies": {
            "mesh_flux": {
                "mean": {"kind": "series", "count": mesh_size, "start": 1.0, "step": 0.01, "scale": scale},
                "std_dev": {"kind": "series", "count": mesh_size, "start": 0.1, "step": 0.001, "scale": scale},
            },
            "mesh_heating": {
                "mean": {"kind": "series", "count": mesh_size, "start": 10.0, "step": 0.1, "scale": scale},
                "std_dev": {"kind": "series", "count": mesh_size, "start": 1.0, "step": 0.01, "scale": scale},
            },
            "blanket_tritium": {
                "mean": [0.25 * scale],
                "std_dev": [0.05 * scale],
            },
        },
    }


def write_fallback_statepoint(path: Path, iteration_id: int, mesh_cfg: dict) -> None:
    payload = build_fallback_statepoint_payload(iteration_id, mesh_cfg)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def is_fallback_statepoint(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return payload.get("format") == FALLBACK_STATEPOINT_FORMAT


class _FallbackTally:
    def __init__(self, mean, std_dev):
        self.mean = np.array(mean, dtype=float)
        self.std_dev = np.array(std_dev, dtype=float)


class _FallbackStatePoint:
    def __init__(self, path: Path):
        self.path = path
        self.payload = json.loads(path.read_text(encoding="utf-8"))

    def get_tally(self, name: str | None = None):
        spec = self.payload["tallies"][name]
        return _FallbackTally(
            mean=_expand_values(spec["mean"]),
            std_dev=_expand_values(spec["std_dev"]),
        )


def _expand_values(spec) -> list[float]:
    if isinstance(spec, list):
        return spec

    if spec["kind"] == "series":
        return _build_series(
            start=float(spec["start"]),
            step=float(spec["step"]),
            count=int(spec["count"]),
            scale=float(spec.get("scale", 1.0)),
        )

    raise ValueError(f"Unsupported fallback tally spec: {spec}")


@contextmanager
def open_statepoint(path: Path, openmc_module=None):
    if is_fallback_statepoint(path):
        yield _FallbackStatePoint(path)
        return

    if openmc_module is None:
        raise ImportError(f"OpenMC is required to read non-fallback statepoint: {path}")

    with openmc_module.StatePoint(str(path)) as statepoint:
        yield statepoint
