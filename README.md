# Paramak OpenMC Dataset Pipeline

This repository generates supervised ML datasets by sampling tokamak geometry and plasma-source parameters, generating CAD with Paramak, running OpenMC transport with DAGMC geometry, and compiling scalar + mesh targets.

Current reactor baseline: `paramak.spherical_tokamak_from_plasma`.

## Bootstrap

1. Initialize repository and submodules:

```bash
git init
git submodule add git@github.com:fusion-energy/paramak.git submodules/paramak
git submodule add git@github.com:fusion-energy/openmc-plasma-source.git submodules/openmc_plasma_source
git submodule update --init --recursive
```

2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Conda environments:

- `environment.yml`: macOS-safe baseline (CAD + data tooling, no OpenMC).
- `environment.openmc-linux.yml`: full Linux OpenMC stack.

Create either environment with:

```bash
mamba env create -f environment.yml
# or
mamba env create -f environment.openmc-linux.yml
```

Note: on macOS, `openmc` is not available for osx-arm64 from conda-forge at the
time of writing, so run the full OpenMC stages on Linux.

When OpenMC is available (typically Linux/conda-forge), ensure the plasma source
submodule is installed in editable mode:

```bash
pip install -e ./submodules/openmc_plasma_source
```

## Pipeline

Default sequence:

```bash
make all
```

Individual stages:

```bash
make doe
make cad
make openmc
make extract
```

Smoke test run:

```bash
make smoke
```

Automated smoke-test suite:

```bash
make test-smoke
```

This uses Python's built-in `unittest` runner, so it works without installing extra test-only packages.

## Project Layout

- `config.yaml`: default full run configuration
- `configs/config.smoke.yaml`: lightweight smoke configuration
- `src/01_generate_doe.py`: DoE generation
- `src/02_build_cad.py`: Paramak to DAGMC export
- `src/03_run_openmc.py`: OpenMC execution
- `src/04_extract_data.py`: statepoint extraction + HDF5 compile
- `src/common/`: shared config, materials, and utility code
- `runs/`: per-iteration working directories
- `dataset/`: compiled outputs
