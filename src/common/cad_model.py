from __future__ import annotations

from typing import Optional

import pandas as pd


DEFAULT_REACTOR_COLORS = {
    "layer_1": (0.4, 0.9, 0.4),
    "layer_2": (0.6, 0.8, 0.6),
    "plasma": (1.0, 0.7, 0.8, 0.6),
    "layer_3": (0.1, 0.1, 0.9),
    "layer_4": (0.4, 0.4, 0.8),
    "layer_5": (0.5, 0.5, 0.8),
}


def build_radial_build(row: pd.Series, layer_type) -> list:
    """Construct a minimal spherical tokamak radial build from sampled parameters."""
    gap_inner = 10.0
    shield_inboard = float(row["center_column_shield_inner_radius"])
    shield_outer = max(10.0, float(row["center_column_shield_outer_radius"]) - shield_inboard)
    plasma_thickness = float(row["minor_radius"]) * 2.0
    gap_outboard = 60.0
    first_wall = 10.0
    blanket = float(row["blanket_thickness"])
    vessel = max(5.0, float(row["divertor_width"]) * 0.25)

    return [
        (layer_type.GAP, gap_inner),
        (layer_type.SOLID, shield_inboard),
        (layer_type.SOLID, shield_outer),
        (layer_type.GAP, 50.0),
        (layer_type.PLASMA, plasma_thickness),
        (layer_type.GAP, gap_outboard),
        (layer_type.SOLID, first_wall),
        (layer_type.SOLID, blanket),
        (layer_type.SOLID, vessel),
    ]


def build_reactor_assembly(
    row: pd.Series,
    paramak_module,
    config: Optional[dict] = None,
    colors: Optional[dict] = None,
):
    """Build the Paramak spherical tokamak assembly for a DOE row."""
    radial_build = build_radial_build(row, paramak_module.LayerType)
    reactor_cfg = {} if config is None else config.get("reactor", {})
    kwargs = {
        "radial_build": radial_build,
        "elongation": float(row["elongation"]),
        "triangularity": float(row["triangularity"]),
        "rotation_angle": float(reactor_cfg.get("rotation_angle", 180.0)),
    }
    if colors is not None:
        kwargs["colors"] = colors
    return paramak_module.spherical_tokamak_from_plasma(**kwargs)
