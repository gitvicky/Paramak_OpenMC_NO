from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from common.cad_model import build_reactor_assembly
from common.config import allow_macos_fallbacks, load_config, platform_system, run_name
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

def convert_step_to_h5m_with_cli(step_path: Path, h5m_path: Path) -> None:
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


def convert_step_to_h5m_with_python(step_path: Path, h5m_path: Path) -> None:
    """Convert STEP to H5M via the cad_to_dagmc Python API when no CLI exists."""
    from cad_to_dagmc import CadToDagmc

    model = CadToDagmc()
    model.add_stp_file(filename=str(step_path), material_tags="assembly_names")
    model.export_dagmc_h5m_file(filename=str(h5m_path))

    if not h5m_path.exists():
        raise RuntimeError("cad_to_dagmc Python API did not produce an h5m file")


def dagmc_material_tags_for_assembly(assembly) -> list[str]:
    """Return one DAGMC/OpenMC material tag for each physical solid in the assembly.

    Paramak's spherical tokamak assembly exports six named solids:
    `layer_1`..`layer_5` plus `plasma`. The old `assembly_names` path produced
    extra names from the STEP hierarchy, which broke cad_to_dagmc. We derive a
    compact, deterministic tag list from the actual assembly solids instead.
    """

    names: Iterable[str] = assembly.names()
    tag_map = {
        "layer_1": "shield",
        "layer_2": "shield",
        "layer_3": "first_wall",
        "layer_4": "blanket",
        "layer_5": "vacuum_vessel",
        "plasma": "vacuum",
    }

    material_tags = []
    for name in names:
        try:
            material_tags.append(tag_map[name])
        except KeyError as exc:
            known = ", ".join(sorted(tag_map))
            raise ValueError(
                f"Unsupported assembly solid name {name!r}. Expected one of: {known}"
            ) from exc

    return material_tags


def convert_assembly_to_h5m_with_python(assembly, h5m_path: Path, config: dict) -> None:
    """Convert a Paramak/CadQuery assembly directly to H5M via Python API."""
    from cad_to_dagmc import CadToDagmc

    mesh_cfg = config.get("cad_to_dagmc_settings", {})
    model = CadToDagmc()
    model.add_cadquery_object(
        cadquery_object=assembly,
        material_tags=dagmc_material_tags_for_assembly(assembly),
    )
    model.export_dagmc_h5m_file(
        filename=str(h5m_path),
        min_mesh_size=float(mesh_cfg.get("min_mesh_size", 10.0)),
        max_mesh_size=float(mesh_cfg.get("max_mesh_size", 25.0)),
        implicit_complement_material_tag="vacuum",
    )

    if not h5m_path.exists():
        raise RuntimeError("cad_to_dagmc Python API did not produce an h5m file")


def convert_step_to_h5m(step_path: Path, h5m_path: Path) -> None:
    """Convert STEP to H5M using the CLI if present, otherwise the Python API."""
    if shutil.which("cad_to_dagmc") is not None:
        convert_step_to_h5m_with_cli(step_path, h5m_path)
        return

    if importlib.util.find_spec("cad_to_dagmc") is not None:
        convert_step_to_h5m_with_python(step_path, h5m_path)
        return

    raise FileNotFoundError("cad_to_dagmc executable or Python package not found")


def write_fallback_h5m(h5m_path: Path, iteration_id: int) -> None:
    h5m_path.write_text(
        f"macos fallback DAGMC placeholder for iteration {iteration_id}\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    macos_fallbacks_allowed = allow_macos_fallbacks(config)
    running_on_macos = platform_system() == "Darwin"
    converter_available = (
        shutil.which("cad_to_dagmc") is not None
        or importlib.util.find_spec("cad_to_dagmc") is not None
    )

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
            "used_fallback_dagmc": False,
            "fallback_reason": None,
            "parameters": row.to_dict(),
            "artifacts": {
                "step": str(step_path),
                "dagmc_h5m": str(h5m_path),
            },
        }

        try:
            assembly = build_reactor_assembly(row, paramak, config=config)
            assembly.save(str(step_path))

            if shutil.which("cad_to_dagmc") is not None:
                convert_step_to_h5m(step_path, h5m_path)
            elif importlib.util.find_spec("cad_to_dagmc") is not None:
                convert_assembly_to_h5m_with_python(assembly, h5m_path, config)
            elif running_on_macos and macos_fallbacks_allowed:
                write_fallback_h5m(h5m_path, iteration_id)
                payload["used_fallback_dagmc"] = True
                payload["fallback_reason"] = "cad_to_dagmc not available on macOS; wrote placeholder h5m"
            else:
                raise FileNotFoundError("cad_to_dagmc executable or Python package not found")

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
    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
