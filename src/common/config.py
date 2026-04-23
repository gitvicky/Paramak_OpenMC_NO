from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Dict, List, Tuple

import yaml


GEOMETRY_KEYS = [
    "major_radius",
    "minor_radius",
    "center_column_shield_inner_radius",
    "center_column_shield_outer_radius",
    "blanket_thickness",
    "divertor_width",
]

PLASMA_KEYS = [
    "ion_density_origin",
    "ion_density_pedestal_fraction",
    "ion_density_separatrix_fraction",
    "ion_density_peaking_factor",
    "ion_temperature_origin",
    "ion_temperature_pedestal_fraction",
    "ion_temperature_separatrix_fraction",
    "ion_temperature_peaking_factor",
    "ion_temperature_beta",
    "elongation",
    "triangularity",
    "shafranov_shift",
    "pedestal_radius_fraction",
]

PARAMETER_COLUMNS = GEOMETRY_KEYS + PLASMA_KEYS


def load_config(config_path: str) -> Dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("Config file must load to a mapping/dictionary")

    validate_config(config)
    return config


def _validate_bounds(bounds: Dict[str, List[float]], group_name: str) -> None:
    for key, value in bounds.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{group_name}.{key} must be a [min, max] pair")
        lo, hi = value
        try:
            lo = float(lo)
            hi = float(hi)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{group_name}.{key} bounds must be numeric, got {value}") from exc
        if lo >= hi:
            raise ValueError(f"{group_name}.{key} must satisfy min < max, got {value}")


def validate_config(config: Dict) -> None:
    required_top = [
        "num_samples",
        "random_seed",
        "execution",
        "geometry_bounds",
        "plasma_source_bounds",
        "openmc_settings",
        "mesh",
        "outputs",
    ]
    for key in required_top:
        if key not in config:
            raise ValueError(f"Missing required top-level config key: {key}")

    if int(config["num_samples"]) <= 0:
        raise ValueError("num_samples must be > 0")

    geometry_bounds = config["geometry_bounds"]
    plasma_bounds = config["plasma_source_bounds"]
    _validate_bounds(geometry_bounds, "geometry_bounds")
    _validate_bounds(plasma_bounds, "plasma_source_bounds")

    for key in GEOMETRY_KEYS:
        if key not in geometry_bounds:
            raise ValueError(f"Missing geometry bound for '{key}'")
    for key in PLASMA_KEYS:
        if key not in plasma_bounds:
            raise ValueError(f"Missing plasma source bound for '{key}'")

    unit_fraction_keys = [
        "ion_density_pedestal_fraction",
        "ion_density_separatrix_fraction",
        "ion_temperature_pedestal_fraction",
        "ion_temperature_separatrix_fraction",
        "pedestal_radius_fraction",
    ]
    for key in unit_fraction_keys:
        lo, hi = plasma_bounds[key]
        if lo < 0.0 or hi > 1.0:
            raise ValueError(f"plasma_source_bounds.{key} must stay within [0, 1]")

    inner = geometry_bounds["center_column_shield_inner_radius"]
    outer = geometry_bounds["center_column_shield_outer_radius"]
    if inner[0] >= outer[1]:
        raise ValueError(
            "Invalid shield bounds: center_column_shield_inner_radius must remain below "
            "center_column_shield_outer_radius"
        )

    major = geometry_bounds["major_radius"]
    minor = geometry_bounds["minor_radius"]
    if major[0] <= minor[0]:
        raise ValueError("major_radius lower bound must be > minor_radius lower bound")

    openmc_settings = config["openmc_settings"]
    for key in ["particles", "batches", "inactive"]:
        if key not in openmc_settings:
            raise ValueError(f"Missing openmc_settings.{key}")
        if int(openmc_settings[key]) < 0:
            raise ValueError(f"openmc_settings.{key} must be >= 0")

    if int(openmc_settings["particles"]) == 0 or int(openmc_settings["batches"]) == 0:
        raise ValueError("openmc_settings.particles and openmc_settings.batches must be > 0")

    mesh = config["mesh"]
    for key in ["dimension", "lower_left", "upper_right"]:
        if key not in mesh:
            raise ValueError(f"Missing mesh.{key}")

    reactor_cfg = config.get("reactor", {})
    if "rotation_angle" in reactor_cfg:
        rotation_angle = float(reactor_cfg["rotation_angle"])
        if rotation_angle <= 0.0 or rotation_angle > 360.0:
            raise ValueError("reactor.rotation_angle must satisfy 0 < angle <= 360")


def parameter_bounds(config: Dict) -> List[Tuple[str, float, float]]:
    bounds = []
    for key in GEOMETRY_KEYS:
        lo, hi = config["geometry_bounds"][key]
        bounds.append((key, float(lo), float(hi)))
    for key in PLASMA_KEYS:
        lo, hi = config["plasma_source_bounds"][key]
        bounds.append((key, float(lo), float(hi)))
    return bounds


def run_name(iteration_id: int, config: Dict) -> str:
    prefix = str(config["execution"].get("run_prefix", "iter_"))
    pad = int(config["execution"].get("run_padding", 6))
    return f"{prefix}{iteration_id:0{pad}d}"


def platform_system() -> str:
    return os.environ.get("PARAMAK_OPENMC_PLATFORM", platform.system())


def allow_macos_fallbacks(config: Dict) -> bool:
    execution_cfg = config.get("execution", {})
    return bool(execution_cfg.get("allow_macos_fallbacks", True))
