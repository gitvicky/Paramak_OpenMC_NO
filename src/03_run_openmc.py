from __future__ import annotations

import argparse
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


def make_source(row: pd.Series):
    try:
        from openmc_plasma_source import tokamak_source
    except Exception:
        return None

    kwargs = {
        "major_radius": float(row["major_radius"]),
        "minor_radius": float(row["minor_radius"]),
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
        "pedestal_radius": float(row["minor_radius"]) * 0.8,
        "shafranov_factor": float(row["shafranov_shift"]),
        "sample_size": 1000,
    }

    try:
        return tokamak_source(**kwargs)
    except Exception:
        return None


def load_openmc_module():
    try:
        import openmc
    except Exception:
        return None
    return openmc


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    openmc = load_openmc_module()
    macos_fallbacks_allowed = allow_macos_fallbacks(config)
    running_on_macos = platform_system() == "Darwin"

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

            dag_universe = openmc.DAGMCUniverse(filename=str(h5m_file))
            geometry = openmc.Geometry(dag_universe)

            materials_by_tag = build_materials(openmc)
            materials = openmc.Materials(list(materials_by_tag.values()))

            settings = openmc.Settings()
            settings.particles = int(config["openmc_settings"]["particles"])
            settings.batches = int(config["openmc_settings"]["batches"])
            settings.inactive = int(config["openmc_settings"]["inactive"])
            settings.statepoint = {"batches": config["openmc_settings"]["statepoint_batches"]}

            source = make_source(row)
            if source is not None:
                settings.source = source
                payload["used_plasma_source"] = True

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
            model.run(cwd=str(run_dir))

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
