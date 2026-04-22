from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import pandas as pd

from common.config import load_config, run_name
from common.io_utils import write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Paramak CAD and export DAGMC h5m")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Skip successful existing runs")
    parser.add_argument("--start-iteration", type=int, default=1)
    parser.add_argument("--end-iteration", type=int, default=None)
    parser.add_argument(
        "--keep-step",
        action="store_true",
        help="Keep intermediate STEP files after DAGMC conversion",
    )
    return parser.parse_args()


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


def convert_step_to_h5m(step_path: Path, h5m_path: Path) -> None:
    """Attempt CAD-to-DAGMC conversion using common cad_to_dagmc CLI shapes."""
    candidate_commands = [
        ["cad_to_dagmc", str(step_path), str(h5m_path)],
        ["cad_to_dagmc", "-i", str(step_path), "-o", str(h5m_path)],
        ["cad_to_dagmc", "--step", str(step_path), "--h5m", str(h5m_path)],
    ]

    errors = []
    for command in candidate_commands:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            if h5m_path.exists():
                return
        except Exception as exc:
            errors.append(f"{' '.join(command)} -> {exc}")

    raise RuntimeError("Failed to convert STEP to H5M. Attempts: " + " | ".join(errors))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    doe_path = Path(config["outputs"]["doe_csv"])
    if not doe_path.exists():
        raise FileNotFoundError(f"DOE file not found: {doe_path}. Run stage 01 first.")

    runs_root = Path(config["execution"]["run_dir"])
    runs_root.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(doe_path)
    if args.end_iteration is not None:
        df = df[df["iteration_id"] <= args.end_iteration]
    df = df[df["iteration_id"] >= args.start_iteration]

    try:
        import paramak
    except Exception as exc:
        raise ImportError(f"Could not import paramak: {exc}") from exc

    success_count = 0
    failed_count = 0

    for _, row in df.iterrows():
        iteration_id = int(row["iteration_id"])
        run_dir = runs_root / run_name(iteration_id, config)
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest = run_dir / config["outputs"]["run_manifest"]
        step_path = run_dir / "geometry.step"
        h5m_path = run_dir / "dagmc.h5m"

        if args.resume and h5m_path.exists() and manifest.exists():
            print(f"[resume] skipping iteration {iteration_id}, found existing dagmc.h5m")
            continue

        t0 = time.time()
        payload = {
            "iteration_id": iteration_id,
            "status": "failed",
            "elapsed_seconds": None,
            "error": None,
            "parameters": row.to_dict(),
            "artifacts": {
                "step": str(step_path),
                "dagmc_h5m": str(h5m_path),
            },
        }

        try:
            radial_build = build_radial_build(row, paramak.LayerType)
            assembly = paramak.spherical_tokamak_from_plasma(
                radial_build=radial_build,
                elongation=float(row["elongation"]),
                triangularity=float(row["triangularity"]),
                rotation_angle=180,
            )
            assembly.save(str(step_path))

            convert_step_to_h5m(step_path, h5m_path)
            if not args.keep_step and step_path.exists():
                step_path.unlink()

            payload["status"] = "completed"
            success_count += 1
        except Exception as exc:
            payload["error"] = repr(exc)
            failed_count += 1
        finally:
            payload["elapsed_seconds"] = round(time.time() - t0, 4)
            write_json(manifest, payload)

    print(f"CAD stage complete. successes={success_count}, failures={failed_count}")


if __name__ == "__main__":
    main()
