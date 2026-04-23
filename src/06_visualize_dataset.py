from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize mesh tallies stored in the compiled neutronics HDF5 dataset"
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
        "--axis",
        choices=["x", "y", "z"],
        default="z",
        help="Axis normal to the slice plane",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Slice index along the chosen axis (defaults to the midpoint)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional image path to save the figure",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the figure interactively",
    )
    return parser.parse_args()


def load_dataset(dataset_path: Path, sample_idx: int):
    if not dataset_path.exists():
        raise FileNotFoundError(f"Compiled dataset not found: {dataset_path}")

    with h5py.File(dataset_path, "r") as h5f:
        dims = tuple(json.loads(h5f["metadata"].attrs["mesh_dimension"]))
        inputs = h5f["inputs"]
        num_samples = int(inputs["iteration_id"].shape[0])
        if sample_idx < 0 or sample_idx >= num_samples:
            raise IndexError(f"Sample index {sample_idx} is out of range for {num_samples} samples")

        iteration_id = int(inputs["iteration_id"][sample_idx])
        flux = h5f["targets/mesh/flux_mean"][sample_idx].reshape(dims)
        heating = h5f["targets/mesh/heating_mean"][sample_idx].reshape(dims)

    return dims, iteration_id, flux, heating


def extract_slice(volume: np.ndarray, axis: str, index: int) -> np.ndarray:
    axis_to_dim = {"x": 0, "y": 1, "z": 2}
    dim = axis_to_dim[axis]
    if index < 0 or index >= volume.shape[dim]:
        raise IndexError(f"Slice index {index} is out of range for axis {axis} with size {volume.shape[dim]}")

    if axis == "x":
        return volume[index, :, :]
    if axis == "y":
        return volume[:, index, :]
    return volume[:, :, index]


def main() -> None:
    args = parse_args()
    dims, iteration_id, flux, heating = load_dataset(args.dataset, args.sample)

    axis_to_dim = {"x": 0, "y": 1, "z": 2}
    selected_dim = axis_to_dim[args.axis]
    slice_index = args.index if args.index is not None else dims[selected_dim] // 2

    flux_slice = extract_slice(flux, args.axis, slice_index)
    heating_slice = extract_slice(heating, args.axis, slice_index)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    flux_im = axes[0].imshow(flux_slice, origin="lower")
    axes[0].set_title(f"Flux mean ({args.axis}={slice_index})")
    fig.colorbar(flux_im, ax=axes[0], shrink=0.9)

    heating_im = axes[1].imshow(heating_slice, origin="lower")
    axes[1].set_title(f"Heating mean ({args.axis}={slice_index})")
    fig.colorbar(heating_im, ax=axes[1], shrink=0.9)

    fig.suptitle(f"Iteration {iteration_id} from {args.dataset.name}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.output, dpi=200, bbox_inches="tight")
        print(f"Wrote figure: {args.output}")

    if args.show or args.output is None:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
