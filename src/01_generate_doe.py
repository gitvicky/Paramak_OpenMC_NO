from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import qmc

from common.config import load_config, parameter_bounds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DOE parameter samples")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing DOE files")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed override (defaults to config random_seed)",
    )
    parser.add_argument(
        "--write-parquet",
        action="store_true",
        help="Write parquet DOE output in addition to CSV",
    )
    parser.add_argument(
        "--corners",
        action="store_true",
        help="Write two DOE rows: one at all lower bounds and one at all upper bounds",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    seed = config["random_seed"] if args.seed is None else args.seed
    n = int(config["num_samples"])

    bounds = parameter_bounds(config)
    names = [b[0] for b in bounds]
    lower = np.array([b[1] for b in bounds], dtype=float)
    upper = np.array([b[2] for b in bounds], dtype=float)

    if args.corners:
        scaled_samples = np.vstack([lower, upper])
    else:
        sampler = qmc.LatinHypercube(d=len(bounds), seed=seed)
        unit_samples = sampler.random(n)
        scaled_samples = qmc.scale(unit_samples, lower, upper)

    df = pd.DataFrame(scaled_samples, columns=names)
    df.insert(0, "iteration_id", np.arange(1, len(df) + 1, dtype=int))

    outputs = config["outputs"]
    csv_path = Path(outputs["doe_csv"])
    parquet_path = Path(outputs["doe_parquet"])

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and not args.overwrite:
        raise FileExistsError(f"DOE file exists: {csv_path}. Use --overwrite to replace.")

    df.to_csv(csv_path, index=False)
    print(f"Wrote DOE CSV: {csv_path} ({len(df)} rows)")

    if args.write_parquet:
        if parquet_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"DOE parquet exists: {parquet_path}. Use --overwrite to replace."
            )
        try:
            df.to_parquet(parquet_path, index=False)
            print(f"Wrote DOE Parquet: {parquet_path}")
        except Exception as exc:
            print(f"Skipped parquet output: {exc}")


if __name__ == "__main__":
    main()
