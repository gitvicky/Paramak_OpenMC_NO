# Paramak OpenMC Dataset Pipeline

This repository generates supervised-learning datasets for tokamak neutronics studies. It:

1. samples reactor and plasma parameters
2. builds Paramak CAD geometry
3. converts geometry to DAGMC
4. runs OpenMC
5. compiles the outputs into an HDF5 dataset

The baseline reactor is `paramak.spherical_tokamak_from_plasma`.

The CAD sweep angle is controlled with:

```yaml
reactor:
  rotation_angle: 360.0
```

Set it to `180.0` for a half-tokamak sector or `360.0` for the full 3D tokamak.

## Materials

The current tokamak model uses a fixed material map for all DOE samples. The DOE changes geometry and plasma/source parameters, but it does not currently vary material compositions or densities.

- `layer_1` and `layer_2` are tagged as `shield`
  - density: `7.9 g/cm3`
  - composition: `Fe 90%`, `C 10%`
- `layer_3` is tagged as `first_wall`
  - density: `7.9 g/cm3`
  - composition: `Fe 70%`, `Cr 20%`, `Ni 10%`
- `layer_4` is tagged as `blanket`
  - density: `10.0 g/cm3`
  - composition: `Li 17%`, `Pb 83%`
- `layer_5` is tagged as `vacuum_vessel`
  - density: `7.9 g/cm3`
  - composition: `Fe 70%`, `Cr 20%`, `Ni 10%`
- `plasma` is tagged as `vacuum`
  - density: `1.0e-12 g/cm3`
  - composition: low-density hydrogen placeholder

These defaults are defined in `src/common/materials.py`, and the CAD-layer to material-tag mapping is defined in `src/02_build_cad.py`.

To make materials part of the DOE, add material parameters to `config.yaml` and `src/common/config.py`, sample them in stage 01, then update `src/common/materials.py` so `build_materials(...)` constructs OpenMC materials from each sampled row instead of using fixed defaults.

## Choose Your Platform

### macOS

macOS can now run the full pipeline with real DAGMC conversion and real OpenMC fixed-source transport, provided the Conda environment and OpenMC nuclear data are installed.

There are two practical macOS modes:

- native `environment.yml` setup for development and visualization
- Conda environment with `openmc`, `dagmc`, `moab`, and `cad_to_dagmc` for exact CAD-to-DAGMC conversion and exact transport

Start with the project environment:

```bash
git clone <your-repo-url>
cd Paramak_OpenMC_NO
git submodule update --init --recursive
conda env create -f environment.yml
conda activate paramak_openmc_no
make all
```

Important:

- On Apple Silicon Macs, the commands above create a native ARM Conda environment.
- `make` now prefers the Conda env `paramak_openmc_no` automatically when it exists.
- `environment.yml` installs `cad_to_dagmc`, `cadquery`, and the visualization stack.
- `cad_to_dagmc` currently expects `cadquery_direct_mesh_plugin` when using its default CadQuery meshing backend, so the environment files install `cadquery-direct-mesh-plugin` via `pip`.
- `config.yaml` and `configs/config.smoke.yaml` now also include:
  - `cad_to_dagmc_settings` for mesh sizing during DAGMC export
  - `openmc_data.cross_sections` for the OpenMC nuclear data path
- `execution.allow_macos_fallbacks: true` still exists, but with the real Conda stack and nuclear data installed the pipeline uses exact outputs rather than placeholders.
- If you want a lighter validation run on macOS, use `make smoke`.

If you need the exact OpenMC stack, install it into the same Conda env:

```bash
conda config --add channels conda-forge
conda config --set channel_priority strict
conda install -c conda-forge cad_to_dagmc
conda install -c conda-forge -y "openmc=0.15.2=dagmc*"
pip install -r requirements.txt
```

This route has been validated in the project environment with:

- `python 3.11`
- `openmc 0.15.2` with a `dagmc_*` build
- `dagmc 3.2.4`
- `moab 5.5.1`
- `cad_to_dagmc 0.7.0`

Note:

- `cad_to_dagmc` from `conda-forge` installs the Python package, but does not provide a `cad_to_dagmc` shell command in this setup.
- The project CAD stage supports the installed Python package directly, so a missing `cad_to_dagmc` CLI is expected and does not mean the converter is unavailable.
- `requirements.txt` and `environment.yml` now install the local `openmc_plasma_source` package as well.
- The default config now requests the exact `openmc_plasma_source.tokamak_source(...)` model in strict mode, so if `NeSST` is missing the OpenMC stage fails instead of silently falling back to a simple point source.

### Linux

Linux is the recommended platform when you want the full pipeline with real OpenMC and DAGMC execution.

```bash
git clone <your-repo-url>
cd Paramak_OpenMC_NO
git submodule update --init --recursive
conda env create -f environment.openmc-linux.yml
conda activate paramak_openmc_no
make all
```

You will also need OpenMC nuclear data configured on the machine for real transport runs.

## OpenMC Nuclear Data

Real OpenMC transport requires an HDF5 cross-section library and `cross_sections.xml`.

This repository is currently configured to use:

```text
.openmc-data/fendl-3.2-hdf5/cross_sections.xml
```

That library can be obtained from the official OpenMC data page:

- https://openmc.org/data/

One working setup is:

```bash
mkdir -p .openmc-data
curl -L https://anl.box.com/shared/static/3cb7jetw7tmxaw6nvn77x6c578jnm2ey.xz -o .openmc-data/fendl32.tar.xz
tar -xJf .openmc-data/fendl32.tar.xz -C .openmc-data
```

After extraction, the repo config already points at the expected file:

```yaml
openmc_data:
  cross_sections: .openmc-data/fendl-3.2-hdf5/cross_sections.xml
```

## What To Run

### Full pipeline

```bash
make all
```

This runs:

```bash
make doe
make cad
make openmc
make extract
```

### Smoke pipeline

```bash
make smoke
```

This runs the same stages using `configs/config.smoke.yaml`.

### Individual stages

```bash
make doe
make cad
make openmc
make extract
```

`make all` now defaults to:

1. `$(CONDA_BASE)/envs/paramak_openmc_no/bin/python` if that env exists
2. `./.venv/bin/python` if present
3. `python3`

## Visualization Tools

The repository includes three different ways to inspect outputs, depending on whether you want to look at geometry, tally data, or both together.

### 1. CAD-only view with Paramak

Script: `src/05_visualize_cad.py`

Use this when you want to inspect the generated reactor geometry itself. It rebuilds the Paramak model for a selected DOE iteration and opens it in the CadQuery viewer, or exports it as `png`, `svg`, or `step`.

Typical commands:

```bash
python src/05_visualize_cad.py --iteration 1 --show
python src/05_visualize_cad.py --iteration 1 --png runs/iter_000001/geometry.png
python src/05_visualize_cad.py --iteration 1 --svg runs/iter_000001/geometry.svg
```

Best for:

- checking the reactor shape generated by `src/02_build_cad.py`
- verifying that sampled geometry parameters produce sensible CAD
- saving quick geometry images for reports or debugging

### 2. OpenMC Plotter for per-run results

Script: `src/08_launch_openmc_plotter.py`

Use this when you want to inspect a completed OpenMC run directly in `openmc-plotter`. The launcher points the plotter at a specific run directory such as `runs/iter_000001`, where `model.xml`, `summary.h5`, and `statepoint.<batches>.h5` already live.

Typical commands:

```bash
python src/08_launch_openmc_plotter.py --iteration 1
python src/08_launch_openmc_plotter.py --run-dir runs/iter_000001
make plotter ITER=1
```

Workflow:

- the script launches `openmc-plotter <run_dir>`
- once the GUI opens, load the matching statepoint from `Edit -> Open StatePoint`
- for a default run this is usually `runs/iter_000001/statepoint.50.h5`

Best for:

- checking tally results directly against the exact OpenMC/DAGMC model
- using the native OpenMC geometry viewer instead of the custom PyVista overlay
- exploring mesh tally data interactively with the model files produced in each run directory

### 3. 2D slices from the compiled HDF5 dataset

Script: `src/06_visualize_dataset.py`

Use this when you want a simple view of the extracted OpenMC mesh tallies stored in `dataset/compiled_neutronics_data.h5`. It reshapes the flattened mesh data back to the configured mesh dimensions and plots 2D slices of `flux_mean` and `heating_mean`.

Typical commands:

```bash
python src/06_visualize_dataset.py --sample 0 --show
python src/06_visualize_dataset.py --sample 0 --axis z --output dataset/flux_heating_slice.png
```

Best for:

- quickly checking whether flux and heating fields look reasonable
- comparing slices through the mesh without opening a 3D viewer
- generating simple figures directly from the compiled dataset

### 4. 3D flux or heating overlay on the CAD model

Script: `src/07_visualize_cad_field_3d.py`

Use this when you want to see the reactor geometry and the OpenMC mesh tally in the same 3D scene. The script rebuilds the matching Paramak reactor from the stored input parameters, reconstructs the OpenMC regular mesh from the HDF5 metadata, and overlays the selected field in `pyvista`.

Typical commands:

```bash
python src/07_visualize_cad_field_3d.py --sample 0 --field flux --mode slices --show
python src/07_visualize_cad_field_3d.py --sample 0 --field flux --mode volume --screenshot dataset/flux_cad_overlay.png
python src/07_visualize_cad_field_3d.py --sample 0 --field heating --mode contours --show
```

Rendering modes:

- `slices`: orthogonal slice planes through the 3D field
- `volume`: semi-transparent volumetric rendering of the field
- `contours`: iso-surfaces highlighting high-value regions

Best for:

- understanding where high flux or heating sits relative to the reactor geometry
- presenting tally results in a more intuitive spatial view
- checking whether the regular mesh bounds line up with the CAD as expected

Note:

- the combined 3D overlay currently shows the CAD as a translucent gray surface
- the flux or heating field carries the color map in the shared scene

### Smoke tests

```bash
make test-smoke
```

## Environment Files

- `environment.yml`: macOS-friendly development environment with CAD conversion support
- `environment.openmc-linux.yml`: Linux environment for full OpenMC runs

If the Linux environment already exists, update it with:

```bash
conda env update -n paramak_openmc_no -f environment.openmc-linux.yml
conda activate paramak_openmc_no
```

## Quick Checks

After activating the environment:

```bash
which python
which python3
python -c "import paramak; print('paramak ok')"
python -c "import pandas, scipy, yaml, h5py; print('core stack ok')"
python -m unittest tests.test_smoke
```

For full-run readiness:

```bash
python -c "import openmc; print('openmc stack ok')"
python -c "import openmc; print(openmc.__version__)"
python -c "import cad_to_dagmc; print(cad_to_dagmc.__version__)"
python -c "import cadquery_direct_mesh_plugin; print('cadquery mesh plugin ok')"
python -c "import openmc_plotter; print('openmc_plotter ok')"
python -c "import pkg_resources; print('pkg_resources ok')"
which openmc
which openmc-plotter
test -f .openmc-data/fendl-3.2-hdf5/cross_sections.xml && echo "cross sections ok"
```

Optional plasma source check:

```bash
python -c "import sys; sys.path.insert(0, 'submodules/openmc_plasma_source/src'); import openmc_plasma_source; import NeSST; print('openmc_plasma_source + NeSST ok')"
```

## Configuration

Main runtime config: `config.yaml`

Useful files:

- `config.yaml`: default run configuration
- `configs/config.smoke.yaml`: lighter smoke-run configuration

Key settings in `config.yaml`:

- `num_samples`: number of designs to generate
- `geometry_bounds`: sampled reactor geometry ranges
- `plasma_source_bounds`: sampled plasma source ranges
- `tokamak_source`: exact OpenMC plasma-source settings passed to `openmc_plasma_source.tokamak_source`
- `openmc_settings`: particles, batches, inactive cycles, statepoints
- `mesh`: mesh tally bounds and resolution
- `cad_to_dagmc_settings`: CAD surface mesh sizing used for DAGMC export
- `openmc_data`: path to `cross_sections.xml`
- `execution`: run directories, worker count, macOS fallback behavior
- `outputs`: dataset and report output paths

## Output Locations

Per-run files are written under `runs/<iteration>/`, including:

- `dagmc.h5m`
- `run_metadata.json`
- `openmc_status.json`
- `statepoint.<batches>.h5`

`openmc_status.json` records whether the exact tokamak plasma source was requested and used. In strict mode, any source-construction failure is reported there and causes the OpenMC stage to fail.

Compiled dataset files are written under `dataset/`, including:

- `doe_parameters.csv`
- `doe_parameters.parquet`
- `compiled_neutronics_data.h5`
- `extraction_report.json`

## Repository Layout

- `Makefile`: pipeline commands
- `src/01_generate_doe.py`: generate sampled input parameters
- `src/02_build_cad.py`: build CAD and export DAGMC geometry
- `src/03_run_openmc.py`: run OpenMC transport
- `src/04_extract_data.py`: extract tallies and compile the dataset
- `src/08_launch_openmc_plotter.py`: launch `openmc-plotter` for a selected run directory
- `src/common/`: shared helpers and config handling
- `tests/test_smoke.py`: smoke tests
- `submodules/paramak`: local Paramak dependency
- `submodules/openmc_plasma_source`: local plasma source dependency

## Clean Outputs

```bash
make clean
```
