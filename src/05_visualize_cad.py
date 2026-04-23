from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common.cad_model import DEFAULT_REACTOR_COLORS, build_reactor_assembly
from common.config import load_config, run_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize or export Paramak CAD for a sampled iteration"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument(
        "--iteration",
        type=int,
        required=True,
        help="DOE iteration_id to visualize",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open the CadQuery viewer",
    )
    parser.add_argument(
        "--png",
        type=Path,
        default=None,
        help="Write a PNG screenshot to this path",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=None,
        help="Write an SVG export to this path",
    )
    parser.add_argument(
        "--step",
        type=Path,
        default=None,
        help="Write a STEP export to this path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to place default outputs in",
    )
    parser.add_argument(
        "--no-colors",
        action="store_true",
        help="Disable Paramak layer colors",
    )
    return parser.parse_args()


def get_iteration_row(doe_path: Path, iteration_id: int) -> pd.Series:
    if not doe_path.exists():
        raise FileNotFoundError(f"DOE file not found: {doe_path}. Run `make doe` first.")

    df = pd.read_csv(doe_path)
    match = df[df["iteration_id"] == iteration_id]
    if match.empty:
        raise ValueError(f"Iteration {iteration_id} not found in DOE file: {doe_path}")
    return match.iloc[0]


def resolve_default_output_dir(args: argparse.Namespace, config: dict, iteration_id: int) -> Path:
    if args.output_dir is not None:
        out_dir = args.output_dir
    else:
        out_dir = Path(config["execution"]["run_dir"]) / run_name(iteration_id, config) / "visualization"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    row = get_iteration_row(Path(config["outputs"]["doe_csv"]), args.iteration)

    try:
        import paramak
    except Exception as exc:
        raise ImportError(f"Could not import paramak: {exc}") from exc

    colors = None if args.no_colors else DEFAULT_REACTOR_COLORS
    assembly = build_reactor_assembly(row, paramak, config=config, colors=colors)

    requested_exports = any(
        value is not None for value in (args.png, args.svg, args.step)
    )
    if not args.show and not requested_exports:
        args.show = True

    output_dir = resolve_default_output_dir(args, config, args.iteration)

    if args.step is not None:
        step_path = args.step
    elif requested_exports:
        step_path = output_dir / "geometry.step"
    else:
        step_path = None

    if args.svg is not None:
        svg_path = args.svg
    elif requested_exports:
        svg_path = output_dir / "geometry.svg"
    else:
        svg_path = None

    if args.png is not None:
        png_path = args.png
    elif requested_exports:
        png_path = output_dir / "geometry.png"
    else:
        png_path = None

    if step_path is not None:
        step_path.parent.mkdir(parents=True, exist_ok=True)
        assembly.save(str(step_path))
        print(f"Wrote STEP: {step_path}")

    if svg_path is not None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        assembly.toCompound().export(str(svg_path))
        print(f"Wrote SVG: {svg_path}")

    if args.show or png_path is not None:
        try:
            from cadquery.vis import show
        except Exception as exc:
            raise ImportError(f"Could not import cadquery.vis.show: {exc}") from exc

        if png_path is not None:
            png_path.parent.mkdir(parents=True, exist_ok=True)
            show(
                assembly,
                screenshot=str(png_path),
                interact=False,
                width=1280,
                height=1024,
                zoom=1.4,
                bgcolor=(1.0, 1.0, 1.0),
            )
            print(f"Wrote PNG: {png_path}")

        if args.show:
            show(assembly)


if __name__ == "__main__":
    main()
