# Linux Cluster Handoff

## Current State

Repository: `Paramak_OpenMC_NO`  
Handoff date: `2026-04-22`

This project is set up with two environment paths:

- `environment.yml`: macOS-safe baseline for CAD + data tooling
- `environment.openmc-linux.yml`: full Linux environment including `openmc`

The macOS machine used during setup is `Darwin arm64`. On this platform:

- `openmc` is not available from `conda-forge`
- `openmc_plasma_source` is not installed in the macOS env
- `cad_to_dagmc` is not installed in the macOS env

## What Was Verified On macOS

The following were confirmed in the existing conda env `paramak_openmc_no`:

- `cadquery` imports successfully
- `paramak` imports successfully
- core packages import successfully: `pandas`, `scipy`, `yaml`, `h5py`
- `environment.yml` resolves cleanly with conda/mamba on macOS ARM

The automated smoke tests were added and pass locally with:

```bash
.venv/bin/python -m unittest tests.test_smoke
```

Result observed:

```text
Ran 3 tests in 2.693s
OK
```

## Pipeline Status On macOS

### Works

- `make doe`
- `make test-smoke`

### Does Not Run End-to-End

- `make cad`
- `make openmc`
- `make extract`
- `make all`
- `make smoke`

### Exact CAD Blocker

A real 1-sample CAD check was run against the current code. The DOE stage succeeded, but CAD failed during STEP to H5M conversion because `cad_to_dagmc` was not available.

Observed failure in `run_metadata.json`:

```text
No such file or directory: 'cad_to_dagmc'
```

Important note: `src/02_build_cad.py` currently prints failures into run manifests but still exits with status code `0`, so `make cad` can appear successful even when all iterations failed.

## Files Added/Updated Recently

- `tests/test_smoke.py`
- `Makefile`
- `README.md`

The smoke test suite uses lightweight stubs so it can validate the pipeline structure without requiring real OpenMC or DAGMC on macOS.

## Recommended Linux Cluster Setup

From the repo root:

```bash
mamba env create -f environment.openmc-linux.yml
conda activate paramak_openmc_no
```

Then confirm the key pieces are available:

```bash
python -c "import openmc, paramak; print('imports_ok')"
python -c "import openmc_plasma_source; print('plasma_source_ok')"
command -v cad_to_dagmc
```

If the environment already exists:

```bash
mamba env update -n paramak_openmc_no -f environment.openmc-linux.yml
conda activate paramak_openmc_no
```

## Suggested First Checks On Linux

1. Verify imports:

```bash
python -c "import openmc, paramak, openmc_plasma_source; print('all_imports_ok')"
```

2. Verify the DAGMC converter:

```bash
cad_to_dagmc --help
```

3. Run the repo smoke suite:

```bash
python -m unittest tests.test_smoke
```

4. Run the project smoke pipeline:

```bash
make smoke
```

5. If that succeeds, run the full pipeline:

```bash
make all
```

## Expected Outputs

Pipeline outputs should appear under:

- `runs/iter_*/`
- `dataset/doe_parameters.csv`
- `dataset/doe_parameters.parquet`
- `dataset/compiled_neutronics_data.h5`
- `dataset/extraction_report.json`

Per-iteration status files:

- `run_metadata.json`
- `openmc_status.json`

## Suggested Next Improvement

Before or during Linux bring-up, it would be worth updating:

- `src/02_build_cad.py`
- `src/03_run_openmc.py`

so they return a non-zero exit code when any iteration fails. Right now failures are recorded, but the stage command itself may still exit successfully, which can hide cluster-side problems.

## Short Summary

The repository is ready to move to Linux for full execution. macOS validation covered the baseline environment, imports for the CAD-side stack, and automated smoke tests. Full CAD-to-DAGMC conversion and OpenMC transport still require Linux, where `cad_to_dagmc` and `openmc` should be installed via `environment.openmc-linux.yml`.
