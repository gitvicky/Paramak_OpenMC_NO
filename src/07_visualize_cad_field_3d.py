from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pyvista as pv

from common.cad_model import build_reactor_assembly


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Overlay compiled mesh tallies on a 3D Paramak CAD view"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("dataset/compiled_neutronics_data.h5"),
        help="Path to compiled HDF5 dataset",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Zero-based sample index to visualize",
    )
    parser.add_argument(
        "--field",
        choices=["flux", "heating"],
        default="flux",
        help="Mesh tally field to render",
    )
    parser.add_argument(
        "--mode",
        choices=["slices", "volume", "contours"],
        default="slices",
        help="How to render the scalar field",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the interactive 3D window",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=None,
        help="Optional image path for a saved screenshot",
    )
    parser.add_argument(
        "--cad-opacity",
        type=float,
        default=0.25,
        help="CAD surface opacity between 0 and 1",
    )
    return parser.parse_args()


def load_sample(dataset_path: Path, sample_idx: int):
    if not dataset_path.exists():
        raise FileNotFoundError(f"Compiled dataset not found: {dataset_path}")

    with h5py.File(dataset_path, "r") as h5f:
        dims = tuple(json.loads(h5f["metadata"].attrs["mesh_dimension"]))
        lower_left = tuple(json.loads(h5f["metadata"].attrs["mesh_lower_left"]))
        upper_right = tuple(json.loads(h5f["metadata"].attrs["mesh_upper_right"]))

        inputs_group = h5f["inputs"]
        num_samples = int(inputs_group["iteration_id"].shape[0])
        if sample_idx < 0 or sample_idx >= num_samples:
            raise IndexError(f"Sample index {sample_idx} is out of range for {num_samples} samples")

        row = {name: inputs_group[name][sample_idx].item() for name in inputs_group.keys()}
        iteration_id = int(row["iteration_id"])
        flux = h5f["targets/mesh/flux_mean"][sample_idx].reshape(dims)
        heating = h5f["targets/mesh/heating_mean"][sample_idx].reshape(dims)

    return pd.Series(row), iteration_id, dims, lower_left, upper_right, flux, heating


def build_uniform_grid(
    dims: tuple[int, int, int],
    lower_left: tuple[float, float, float],
    upper_right: tuple[float, float, float],
    values: np.ndarray,
    field_name: str,
):
    spacing = tuple(
        (upper_right[i] - lower_left[i]) / float(dims[i]) for i in range(3)
    )
    grid = pv.ImageData(
        dimensions=(dims[0] + 1, dims[1] + 1, dims[2] + 1),
        spacing=spacing,
        origin=lower_left,
    )
    grid.cell_data[field_name] = np.asarray(values, dtype=float).ravel(order="F")
    return grid.cell_data_to_point_data()


def build_cad_mesh(row: pd.Series):
    try:
        import paramak
    except Exception as exc:
        raise ImportError(f"Could not import paramak: {exc}") from exc

    assembly = build_reactor_assembly(row, paramak)

    with tempfile.TemporaryDirectory() as tmpdir:
        stl_path = Path(tmpdir) / "reactor.stl"
        assembly.toCompound().export(str(stl_path))
        return pv.read(str(stl_path))


def add_field_actor(plotter: pv.Plotter, grid, field_name: str, mode: str) -> None:
    scalar_bar_args = {"title": field_name.replace("_", " ").title()}

    if mode == "volume":
        plotter.add_volume(
            grid,
            scalars=field_name,
            cmap="inferno",
            opacity="sigmoid",
            scalar_bar_args=scalar_bar_args,
        )
        return

    if mode == "contours":
        values = grid[field_name]
        positive = values[np.isfinite(values) & (values > 0.0)]
        if positive.size == 0:
            levels = np.linspace(np.nanmin(values), np.nanmax(values), 5)
        else:
            levels = np.quantile(positive, [0.6, 0.75, 0.85, 0.93, 0.98])
        contour_mesh = grid.contour(isosurfaces=np.unique(levels), scalars=field_name)
        plotter.add_mesh(
            contour_mesh,
            scalars=field_name,
            cmap="inferno",
            opacity=0.55,
            scalar_bar_args=scalar_bar_args,
        )
        return

    bounds = grid.bounds
    slices = grid.slice_orthogonal(
        x=0.5 * (bounds[0] + bounds[1]),
        y=0.5 * (bounds[2] + bounds[3]),
        z=0.5 * (bounds[4] + bounds[5]),
    )
    plotter.add_mesh(
        slices,
        scalars=field_name,
        cmap="inferno",
        scalar_bar_args=scalar_bar_args,
    )


def main() -> None:
    args = parse_args()
    row, iteration_id, dims, lower_left, upper_right, flux, heating = load_sample(
        args.dataset,
        args.sample,
    )

    field_values = flux if args.field == "flux" else heating
    field_name = f"{args.field}_mean"
    grid = build_uniform_grid(dims, lower_left, upper_right, field_values, field_name)
    cad_mesh = build_cad_mesh(row)

    plotter = pv.Plotter(off_screen=args.screenshot is not None and not args.show)
    plotter.set_background("white")

    add_field_actor(plotter, grid, field_name, args.mode)
    plotter.add_mesh(
        cad_mesh,
        color="lightgray",
        opacity=args.cad_opacity,
        smooth_shading=True,
        show_edges=False,
    )
    plotter.add_axes()
    plotter.show_grid()
    plotter.add_text(
        f"Iteration {iteration_id} | {field_name} | mode={args.mode}",
        position="upper_left",
        font_size=10,
    )

    if args.screenshot is not None:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        plotter.show(screenshot=str(args.screenshot), auto_close=False)
        print(f"Wrote screenshot: {args.screenshot}")
        plotter.close()
        return

    if args.show or args.screenshot is None:
        plotter.show()


if __name__ == "__main__":
    main()
