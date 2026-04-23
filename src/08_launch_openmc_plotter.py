from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common.config import load_config, run_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch openmc-plotter for a completed run directory"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
        help="DOE iteration_id to visualize",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Optional explicit run directory override",
    )
    parser.add_argument(
        "--statepoint",
        type=Path,
        default=None,
        help="Optional explicit statepoint path override",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Pass --clear-cache to openmc-plotter on startup",
    )
    return parser.parse_args()


def resolve_run_dir(args: argparse.Namespace, config: dict) -> Path:
    if args.run_dir is not None:
        return args.run_dir.resolve()
    runs_root = Path(config["execution"]["run_dir"])
    return (runs_root / run_name(args.iteration, config)).resolve()


def resolve_statepoint(args: argparse.Namespace, config: dict, run_dir: Path) -> Path:
    if args.statepoint is not None:
        return args.statepoint.resolve()

    batches = int(config["openmc_settings"]["batches"])
    candidate = run_dir / f"statepoint.{batches}.h5"
    if candidate.exists():
        return candidate.resolve()

    matches = sorted(run_dir.glob("statepoint.*.h5"))
    if not matches:
        raise FileNotFoundError(f"No statepoint file found in {run_dir}")
    return matches[-1].resolve()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    run_dir = resolve_run_dir(args, config)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    model_xml = run_dir / "model.xml"
    if not model_xml.exists():
        raise FileNotFoundError(f"Expected OpenMC model file not found: {model_xml}")

    summary_h5 = run_dir / "summary.h5"
    if not summary_h5.exists():
        print(f"Warning: summary file not found: {summary_h5}")

    statepoint = resolve_statepoint(args, config, run_dir)
    candidate_bins = [
        Path(sys.executable).resolve().parent / "openmc-plotter",
    ]
    system_bin = shutil.which("openmc-plotter")
    if system_bin is not None:
        candidate_bins.append(Path(system_bin))

    plotter_bin = next((str(path) for path in candidate_bins if path.exists()), None)
    if plotter_bin is None:
        raise FileNotFoundError(
            "Could not find 'openmc-plotter' on PATH. Install it with "
            "'conda install -c conda-forge openmc-plotter' or "
            "'python -m pip install openmc-plotter'."
        )

    cmd = [plotter_bin]
    if args.clear_cache:
        cmd.append("--clear-cache")
    cmd.append(str(run_dir))

    print(f"Launching openmc-plotter in: {run_dir}")
    print(f"Model file: {model_xml}")
    print(f"Statepoint to load in the GUI: {statepoint}")
    print("In openmc-plotter, use Edit -> Open StatePoint to load the tally results.")

    subprocess.run(cmd, cwd=run_dir, check=True)


if __name__ == "__main__":
    main()
