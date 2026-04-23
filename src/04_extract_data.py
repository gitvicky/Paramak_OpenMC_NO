from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import h5py
import numpy as np
import pandas as pd

from common.config import PARAMETER_COLUMNS, load_config, run_name
from common.fallback_openmc import open_statepoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract OpenMC outputs into compiled HDF5 dataset")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--start-iteration", type=int, default=1)
    parser.add_argument("--end-iteration", type=int, default=None)
    return parser.parse_args()


def read_tally_means_std(sp, tally_name: str):
    tally = sp.get_tally(name=tally_name)
    means = tally.mean.ravel()
    stds = tally.std_dev.ravel()
    return means, stds


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    try:
        import openmc
    except Exception:
        openmc = None

    doe = pd.read_csv(config["outputs"]["doe_csv"])
    if args.end_iteration is not None:
        doe = doe[doe["iteration_id"] <= args.end_iteration]
    doe = doe[doe["iteration_id"] >= args.start_iteration]

    runs_root = Path(config["execution"]["run_dir"])
    h5_path = Path(config["outputs"]["compiled_hdf5"])
    report_path = Path(config["outputs"]["extraction_report"])
    h5_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[Dict] = []
    scalar_mean = []
    scalar_std = []
    mesh_flux_mean = []
    mesh_flux_std = []
    mesh_heating_mean = []
    mesh_heating_std = []

    expected_statepoint = f"statepoint.{int(config['openmc_settings']['batches'])}.h5"
    missing_statepoint = 0
    missing_tally = 0

    for _, row in doe.iterrows():
        iteration_id = int(row["iteration_id"])
        run_dir = runs_root / run_name(iteration_id, config)
        statepoint_path = run_dir / expected_statepoint

        if not statepoint_path.exists():
            missing_statepoint += 1
            continue

        with open_statepoint(statepoint_path, openmc) as sp:
            try:
                tbr_mean, tbr_std = read_tally_means_std(sp, "blanket_tritium")
                flux_mean, flux_std = read_tally_means_std(sp, "mesh_flux")
                heat_mean, heat_std = read_tally_means_std(sp, "mesh_heating")
            except Exception:
                missing_tally += 1
                continue

        records.append({"iteration_id": iteration_id})
        scalar_mean.append(float(np.sum(tbr_mean)))
        scalar_std.append(float(np.sqrt(np.sum(np.square(tbr_std)))))
        mesh_flux_mean.append(flux_mean)
        mesh_flux_std.append(flux_std)
        mesh_heating_mean.append(heat_mean)
        mesh_heating_std.append(heat_std)

    if not records:
        raise RuntimeError("No valid statepoints found for extraction.")

    valid_ids = {r["iteration_id"] for r in records}
    inputs_df = doe[doe["iteration_id"].isin(valid_ids)].copy()
    inputs_df = inputs_df[["iteration_id", *PARAMETER_COLUMNS]].sort_values("iteration_id")

    order = inputs_df["iteration_id"].tolist()
    id_to_idx = {r["iteration_id"]: i for i, r in enumerate(records)}

    scalar_mean_arr = np.array([scalar_mean[id_to_idx[i]] for i in order], dtype=float)
    scalar_std_arr = np.array([scalar_std[id_to_idx[i]] for i in order], dtype=float)

    flux_mean_arr = np.stack([mesh_flux_mean[id_to_idx[i]] for i in order], axis=0)
    flux_std_arr = np.stack([mesh_flux_std[id_to_idx[i]] for i in order], axis=0)
    heat_mean_arr = np.stack([mesh_heating_mean[id_to_idx[i]] for i in order], axis=0)
    heat_std_arr = np.stack([mesh_heating_std[id_to_idx[i]] for i in order], axis=0)

    with h5py.File(h5_path, "w") as h5f:
        g_inputs = h5f.create_group("inputs")
        for col in inputs_df.columns:
            g_inputs.create_dataset(col, data=inputs_df[col].to_numpy())

        g_scalar = h5f.create_group("targets/scalar")
        g_scalar.create_dataset("blanket_tritium_mean", data=scalar_mean_arr)
        g_scalar.create_dataset("blanket_tritium_std", data=scalar_std_arr)

        g_mesh = h5f.create_group("targets/mesh")
        g_mesh.create_dataset("flux_mean", data=flux_mean_arr)
        g_mesh.create_dataset("flux_std", data=flux_std_arr)
        g_mesh.create_dataset("heating_mean", data=heat_mean_arr)
        g_mesh.create_dataset("heating_std", data=heat_std_arr)

        g_meta = h5f.create_group("metadata")
        g_meta.attrs["mesh_dimension"] = json.dumps(config["mesh"]["dimension"])
        g_meta.attrs["mesh_lower_left"] = json.dumps(config["mesh"]["lower_left"])
        g_meta.attrs["mesh_upper_right"] = json.dumps(config["mesh"]["upper_right"])
        g_meta.attrs["num_samples_extracted"] = len(inputs_df)

    report = {
        "requested_iterations": int(len(doe)),
        "extracted_iterations": int(len(inputs_df)),
        "missing_statepoint": int(missing_statepoint),
        "missing_expected_tallies": int(missing_tally),
        "compiled_hdf5": str(h5_path),
    }
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    print(f"Compiled dataset written: {h5_path}")
    print(f"Extraction report written: {report_path}")
    print(f"Extracted iterations: {len(inputs_df)}")


if __name__ == "__main__":
    main()
