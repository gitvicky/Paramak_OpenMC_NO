from __future__ import annotations

import argparse
import inspect
import os
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

from common.config import allow_macos_fallbacks, load_config, platform_system, run_name
from common.fallback_openmc import write_fallback_statepoint
from common.io_utils import read_json, write_json
from common.materials import build_materials


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenMC transport for each CAD iteration")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--start-iteration", type=int, default=1)
    parser.add_argument("--end-iteration", type=int, default=None)
    return parser.parse_args()


def build_mesh_tally(openmc_module, mesh_cfg: dict):
    mesh = openmc_module.RegularMesh()
    mesh.dimension = mesh_cfg["dimension"]
    mesh.lower_left = mesh_cfg["lower_left"]
    mesh.upper_right = mesh_cfg["upper_right"]

    mesh_filter = openmc_module.MeshFilter(mesh)

    flux_tally = openmc_module.Tally(name="mesh_flux")
    flux_tally.filters = [mesh_filter]
    flux_tally.scores = ["flux"]

    heating_tally = openmc_module.Tally(name="mesh_heating")
    heating_tally.filters = [mesh_filter]
    heating_tally.scores = ["heating"]

    return [flux_tally, heating_tally]


TOKAMAK_SOURCE_KEYS = {
    "major_radius",
    "minor_radius",
    "elongation",
    "triangularity",
    "mode",
    "ion_density_centre",
    "ion_density_peaking_factor",
    "ion_density_pedestal",
    "ion_density_separatrix",
    "ion_temperature_centre",
    "ion_temperature_peaking_factor",
    "ion_temperature_beta",
    "ion_temperature_pedestal",
    "ion_temperature_separatrix",
    "pedestal_radius",
    "shafranov_factor",
    "angles",
    "sample_size",
    "fuel",
    "sample_seed",
}


def build_tokamak_source_kwargs(row: pd.Series, config: dict) -> dict:
    source_cfg = dict(config.get("tokamak_source", {}))
    major_radius = float(row["major_radius"])
    minor_radius = float(row["minor_radius"])

    kwargs = {
        "major_radius": major_radius,
        "minor_radius": minor_radius,
        "elongation": float(row["elongation"]),
        "triangularity": float(row["triangularity"]),
        "mode": "H",
        "ion_density_centre": float(row["ion_density_origin"]),
        "ion_density_peaking_factor": 1.0,
        "ion_density_pedestal": float(row["ion_density_origin"]) * 0.7,
        "ion_density_separatrix": float(row["ion_density_origin"]) * 0.2,
        "ion_temperature_centre": float(row["ion_temperature_origin"]) * 1.0e3,
        "ion_temperature_peaking_factor": 1.0,
        "ion_temperature_beta": 1.0,
        "ion_temperature_pedestal": float(row["ion_temperature_origin"]) * 0.6e3,
        "ion_temperature_separatrix": float(row["ion_temperature_origin"]) * 0.2e3,
        "pedestal_radius": minor_radius * 0.8,
        "shafranov_factor": float(row["shafranov_shift"]),
        "sample_size": 1000,
        "fuel": {"D": 0.5, "T": 0.5},
    }

    pedestal_radius_fraction = source_cfg.pop("pedestal_radius_fraction", None)
    for key, value in source_cfg.items():
        if key in {"enabled", "strict"}:
            continue
        if key in TOKAMAK_SOURCE_KEYS:
            kwargs[key] = value

    if pedestal_radius_fraction is not None:
        kwargs["pedestal_radius"] = minor_radius * float(pedestal_radius_fraction)

    if "angles" in kwargs:
        kwargs["angles"] = tuple(float(value) for value in kwargs["angles"])

    if "fuel" in kwargs:
        kwargs["fuel"] = {str(key): float(value) for key, value in kwargs["fuel"].items()}

    numeric_keys = TOKAMAK_SOURCE_KEYS - {"mode", "angles", "fuel"}
    for key in numeric_keys:
        if key in kwargs:
            kwargs[key] = float(kwargs[key]) if key != "sample_size" else int(kwargs[key])

    return kwargs


def make_source(row: pd.Series, config: dict):
    kwargs = build_tokamak_source_kwargs(row, config)
    try:
        from openmc_plasma_source import tokamak_source
    except Exception as exc:
        repo_root = Path(__file__).resolve().parents[1]
        plasma_src = repo_root / "submodules" / "openmc_plasma_source" / "src"
        if plasma_src.exists():
            sys.path.insert(0, str(plasma_src))
            try:
                from openmc_plasma_source import tokamak_source
            except Exception as inner_exc:
                return None, kwargs, repr(inner_exc)
        else:
            return None, kwargs, repr(exc)

    try:
        return tokamak_source(**kwargs), kwargs, None
    except Exception as exc:
        return None, kwargs, repr(exc)


def make_default_source(openmc_module, row: pd.Series):
    """Provide an explicit fallback source for fixed-source transport runs."""
    if not hasattr(openmc_module, "IndependentSource"):
        return None

    source = openmc_module.IndependentSource()
    source.space = openmc_module.stats.Point((float(row["major_radius"]), 0.0, 0.0))
    source.angle = openmc_module.stats.Isotropic()
    source.energy = openmc_module.stats.Discrete([14.08e6], [1.0])
    return source


def load_openmc_module():
    try:
        import openmc
    except Exception:
        return None
    return openmc


def resolve_openmc_executable() -> str:
    """Find the OpenMC CLI that matches the active Python environment."""
    python_bin = Path(sys.executable).resolve()
    candidates = []

    if python_bin.exists():
        candidates.append(python_bin.parent / "openmc")

    system_openmc = shutil.which("openmc")
    if system_openmc:
        candidates.append(Path(system_openmc))

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError("Could not find the openmc executable")


def build_geometry(openmc_module, h5m_file: Path):
    """Build geometry using a bounded DAGMC universe when the API supports it."""
    dag_universe = openmc_module.DAGMCUniverse(filename=str(h5m_file))
    if hasattr(dag_universe, "bounded_universe"):
        return openmc_module.Geometry(
            dag_universe.bounded_universe(
                bounded_type="sphere",
                boundary_type="vacuum",
                padding_distance=10.0,
            )
        )
    return openmc_module.Geometry(dag_universe)


def run_model(model, run_dir: Path) -> None:
    """Run OpenMC with the env-local executable when supported by the API."""
    run_sig = inspect.signature(model.run)
    kwargs = {"cwd": str(run_dir)}

    if "openmc_exec" in run_sig.parameters:
        kwargs["openmc_exec"] = resolve_openmc_executable()

    model.run(**kwargs)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    openmc = load_openmc_module()
    macos_fallbacks_allowed = allow_macos_fallbacks(config)
    running_on_macos = platform_system() == "Darwin"
    tokamak_source_cfg = config.get("tokamak_source", {})
    tokamak_source_enabled = bool(tokamak_source_cfg.get("enabled", True))
    tokamak_source_strict = bool(tokamak_source_cfg.get("strict", False))

    doe = pd.read_csv(config["outputs"]["doe_csv"]) 
    if args.end_iteration is not None:
        doe = doe[doe["iteration_id"] <= args.end_iteration]
    doe = doe[doe["iteration_id"] >= args.start_iteration]

    runs_root = Path(config["execution"]["run_dir"])

    completed = 0
    failed = 0

    for _, row in doe.iterrows():
        iteration_id = int(row["iteration_id"])
        run_dir = runs_root / run_name(iteration_id, config)
        h5m_file = run_dir / "dagmc.h5m"

        if not h5m_file.exists():
            continue

        status_path = run_dir / config["outputs"]["openmc_manifest"]
        statepoint_name = f"statepoint.{int(config['openmc_settings']['batches'])}.h5"
        statepoint_path = run_dir / statepoint_name

        if args.resume and status_path.exists() and statepoint_path.exists():
            print(f"[resume] skipping iteration {iteration_id}, statepoint already present")
            continue

        t0 = time.time()
        payload = {
            "iteration_id": iteration_id,
            "status": "failed",
            "elapsed_seconds": None,
            "error": None,
            "statepoint": str(statepoint_path),
            "used_plasma_source": False,
            "plasma_source_requested": tokamak_source_enabled,
            "plasma_source_type": "tokamak" if tokamak_source_enabled else None,
            "plasma_source_error": None,
            "plasma_source_kwargs": None,
            "used_fallback_statepoint": False,
            "fallback_reason": None,
        }

        try:
            manifest_path = run_dir / config["outputs"]["run_manifest"]
            cad_manifest = read_json(manifest_path) if manifest_path.exists() else {}
            fallback_due_to_placeholder_dagmc = bool(cad_manifest.get("used_fallback_dagmc"))

            should_use_fallback = fallback_due_to_placeholder_dagmc or (
                openmc is None and running_on_macos and macos_fallbacks_allowed
            )

            if should_use_fallback:
                write_fallback_statepoint(statepoint_path, iteration_id, config["mesh"])
                payload["used_fallback_statepoint"] = True
                if fallback_due_to_placeholder_dagmc:
                    payload["fallback_reason"] = "CAD stage used placeholder DAGMC on macOS"
                else:
                    payload["fallback_reason"] = "openmc not available on macOS; wrote fallback statepoint"
                payload["status"] = "completed"
                completed += 1
                continue

            if openmc is None:
                raise ImportError("Could not import openmc")

            geometry = build_geometry(openmc, h5m_file)

            materials_by_tag = build_materials(openmc)
            materials = openmc.Materials(list(materials_by_tag.values()))
            cross_sections = config.get("openmc_data", {}).get("cross_sections")
            if cross_sections:
                cross_sections_path = Path(cross_sections)
                if not cross_sections_path.exists():
                    raise FileNotFoundError(
                        f"Configured OpenMC cross sections file not found: {cross_sections_path}"
                    )
                materials.cross_sections = str(cross_sections_path)

            settings = openmc.Settings()
            settings.run_mode = "fixed source"
            settings.particles = int(config["openmc_settings"]["particles"])
            settings.batches = int(config["openmc_settings"]["batches"])
            settings.inactive = int(config["openmc_settings"]["inactive"])
            settings.statepoint = {"batches": config["openmc_settings"]["statepoint_batches"]}

            source = None
            if tokamak_source_enabled:
                source, source_kwargs, source_error = make_source(row, config)
                payload["plasma_source_kwargs"] = source_kwargs
                payload["plasma_source_error"] = source_error
            if source is not None:
                settings.source = source
                payload["used_plasma_source"] = True
            else:
                if tokamak_source_enabled and tokamak_source_strict:
                    raise RuntimeError(
                        "Strict tokamak plasma source requested, but source creation failed. "
                        f"Details: {payload['plasma_source_error']}"
                    )
                default_source = make_default_source(openmc, row)
                if default_source is not None:
                    settings.source = default_source

            tallies = openmc.Tallies(build_mesh_tally(openmc, config["mesh"]))

            tbr_tally = openmc.Tally(name="blanket_tritium")
            tbr_tally.scores = ["H3-production"]
            tallies.append(tbr_tally)

            model = openmc.Model(
                geometry=geometry,
                materials=materials,
                settings=settings,
                tallies=tallies,
            )
            run_model(model, run_dir)

            payload["status"] = "completed"
            completed += 1
        except Exception as exc:
            payload["error"] = repr(exc)
            failed += 1
        finally:
            payload["elapsed_seconds"] = round(time.time() - t0, 4)
            write_json(status_path, payload)

    print(f"OpenMC stage complete. completed={completed}, failed={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
