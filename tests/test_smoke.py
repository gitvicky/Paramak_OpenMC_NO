from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import h5py
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_command(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def write_test_config(tmp_path: Path) -> Path:
    with (REPO_ROOT / "configs" / "config.smoke.yaml").open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)

    config["execution"]["run_dir"] = str(tmp_path / "runs")
    config["execution"]["dataset_dir"] = str(tmp_path / "dataset")
    config["outputs"]["doe_csv"] = str(tmp_path / "dataset" / "doe_parameters.csv")
    config["outputs"]["doe_parquet"] = str(tmp_path / "dataset" / "doe_parameters.parquet")
    config["outputs"]["compiled_hdf5"] = str(tmp_path / "dataset" / "compiled_neutronics_data.h5")
    config["outputs"]["extraction_report"] = str(tmp_path / "dataset" / "extraction_report.json")

    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, sort_keys=False)

    return config_path


def make_stub_environment(tmp_path: Path) -> dict[str, str]:
    stub_root = tmp_path / "stubs"
    stub_root.mkdir()

    (stub_root / "paramak.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            class LayerType:
                GAP = "gap"
                SOLID = "solid"
                PLASMA = "plasma"

            class Assembly:
                def save(self, filename):
                    Path(filename).write_text("stub step", encoding="utf-8")

            def spherical_tokamak_from_plasma(**kwargs):
                return Assembly()
            """
        ),
        encoding="utf-8",
    )

    (stub_root / "openmc.py").write_text(
        textwrap.dedent(
            """
            import json
            from pathlib import Path
            import numpy as np

            class Material:
                def __init__(self, name=None):
                    self.name = name

                def set_density(self, *args, **kwargs):
                    return None

                def add_element(self, *args, **kwargs):
                    return None

            class Materials(list):
                pass

            class Settings:
                def __init__(self):
                    self.particles = None
                    self.batches = None
                    self.inactive = None
                    self.statepoint = None
                    self.source = None

            class DAGMCUniverse:
                def __init__(self, filename):
                    self.filename = filename

            class Geometry:
                def __init__(self, universe):
                    self.universe = universe

            class RegularMesh:
                def __init__(self):
                    self.dimension = None
                    self.lower_left = None
                    self.upper_right = None

            class MeshFilter:
                def __init__(self, mesh):
                    self.mesh = mesh

            class Tally:
                def __init__(self, name=None):
                    self.name = name
                    self.filters = []
                    self.scores = []
                    self.mean = np.array([])
                    self.std_dev = np.array([])

            class Tallies(list):
                pass

            class Model:
                def __init__(self, geometry=None, materials=None, settings=None, tallies=None):
                    self.geometry = geometry
                    self.materials = materials
                    self.settings = settings
                    self.tallies = tallies or []

                def run(self, cwd=None):
                    batches = int(self.settings.batches)
                    statepoint_path = Path(cwd) / f"statepoint.{batches}.h5"
                    payload = {}
                    for tally in self.tallies:
                        if tally.name == "mesh_flux":
                            payload[tally.name] = {
                                "mean": [1.0, 2.0, 3.0, 4.0],
                                "std_dev": [0.1, 0.2, 0.3, 0.4],
                            }
                        elif tally.name == "mesh_heating":
                            payload[tally.name] = {
                                "mean": [10.0, 20.0, 30.0, 40.0],
                                "std_dev": [1.0, 2.0, 3.0, 4.0],
                            }
                        elif tally.name == "blanket_tritium":
                            payload[tally.name] = {
                                "mean": [0.25],
                                "std_dev": [0.05],
                            }
                    statepoint_path.write_text(json.dumps(payload), encoding="utf-8")
                    return str(statepoint_path)

            class StatePoint:
                def __init__(self, filename):
                    self.filename = filename
                    self._payload = json.loads(Path(filename).read_text(encoding="utf-8"))

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def get_tally(self, name=None):
                    values = self._payload[name]
                    tally = Tally(name=name)
                    tally.mean = np.array(values["mean"], dtype=float)
                    tally.std_dev = np.array(values["std_dev"], dtype=float)
                    return tally
            """
        ),
        encoding="utf-8",
    )

    plasma_pkg = stub_root / "openmc_plasma_source"
    plasma_pkg.mkdir()
    (plasma_pkg / "__init__.py").write_text(
        textwrap.dedent(
            """
            def tokamak_source(**kwargs):
                return {"kind": "stub_source", "kwargs": kwargs}
            """
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    converter = bin_dir / "cad_to_dagmc"
    converter.write_text(
        textwrap.dedent(
            """\
#!/usr/bin/env python3
import sys
from pathlib import Path


def resolve_output(arguments):
    if len(arguments) == 2:
        return Path(arguments[1])
    if "-o" in arguments:
        return Path(arguments[arguments.index("-o") + 1])
    if "--h5m" in arguments:
        return Path(arguments[arguments.index("--h5m") + 1])
    raise SystemExit("missing output path")


output_path = resolve_output(sys.argv[1:])
output_path.write_text("stub dagmc", encoding="utf-8")
"""
        ),
        encoding="utf-8",
    )
    converter.chmod(converter.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(stub_root) if not existing_pythonpath else f"{stub_root}{os.pathsep}{existing_pythonpath}"
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


class SmokeTests(unittest.TestCase):
    def test_generate_doe_smoke(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = write_test_config(tmp_path)

            run_command(
                [sys.executable, "src/01_generate_doe.py", "--config", str(config_path), "--write-parquet"],
                cwd=REPO_ROOT,
            )

            csv_path = tmp_path / "dataset" / "doe_parameters.csv"
            parquet_path = tmp_path / "dataset" / "doe_parameters.parquet"

            self.assertTrue(csv_path.exists())
            if parquet_path.exists():
                self.assertGreater(parquet_path.stat().st_size, 0)

            df = pd.read_csv(csv_path)
            self.assertEqual(len(df), 5)
            self.assertEqual(list(df["iteration_id"]), [1, 2, 3, 4, 5])

    def test_full_pipeline_smoke_with_stubbed_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = write_test_config(tmp_path)
            env = make_stub_environment(tmp_path)

            run_command(
                ["make", "all", f"CONFIG={config_path}", f"PYTHON={sys.executable}"],
                cwd=REPO_ROOT,
                env=env,
            )

            dataset_dir = tmp_path / "dataset"
            runs_dir = tmp_path / "runs"
            compiled_hdf5 = dataset_dir / "compiled_neutronics_data.h5"
            report_path = dataset_dir / "extraction_report.json"

            self.assertTrue(compiled_hdf5.exists())
            self.assertTrue(report_path.exists())

            with report_path.open("r", encoding="utf-8") as stream:
                report = json.load(stream)
            self.assertEqual(report["requested_iterations"], 5)
            self.assertEqual(report["extracted_iterations"], 5)
            self.assertEqual(report["missing_statepoint"], 0)
            self.assertEqual(report["missing_expected_tallies"], 0)

            with h5py.File(compiled_hdf5, "r") as h5f:
                self.assertEqual(h5f["inputs"]["iteration_id"].shape, (5,))
                self.assertEqual(h5f["targets/scalar"]["blanket_tritium_mean"].shape, (5,))
                self.assertEqual(h5f["targets/mesh"]["flux_mean"].shape, (5, 4))
                self.assertEqual(h5f["targets/mesh"]["heating_mean"].shape, (5, 4))
                self.assertEqual(h5f["metadata"].attrs["num_samples_extracted"], 5)

            for iteration_id in range(1, 6):
                run_dir = runs_dir / f"iter_{iteration_id:04d}"
                self.assertTrue((run_dir / "dagmc.h5m").exists())
                self.assertTrue((run_dir / "run_metadata.json").exists())
                self.assertTrue((run_dir / "openmc_status.json").exists())
                self.assertTrue((run_dir / "statepoint.5.h5").exists())

    def test_make_smoke_target_exists(self):
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("smoke:", makefile)
        self.assertIn("test-smoke:", makefile)

    def test_macos_fallback_pipeline_without_openmc_or_converter(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = write_test_config(tmp_path)

            stub_root = tmp_path / "stubs"
            stub_root.mkdir()
            (stub_root / "paramak.py").write_text(
                textwrap.dedent(
                    """
                    from pathlib import Path

                    class LayerType:
                        GAP = "gap"
                        SOLID = "solid"
                        PLASMA = "plasma"

                    class Assembly:
                        def save(self, filename):
                            Path(filename).write_text("stub step", encoding="utf-8")

                    def spherical_tokamak_from_plasma(**kwargs):
                        return Assembly()
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(stub_root)
            env["PARAMAK_OPENMC_PLATFORM"] = "Darwin"
            repo_venv_python = REPO_ROOT / ".venv" / "bin" / "python"
            if repo_venv_python.exists():
                fallback_python = str(repo_venv_python)
            else:
                fallback_python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else shutil.which("python3") or "python3"

            run_command(
                ["make", "all", f"CONFIG={config_path}", f"PYTHON={fallback_python}"],
                cwd=REPO_ROOT,
                env=env,
            )

            report_path = tmp_path / "dataset" / "extraction_report.json"
            compiled_hdf5 = tmp_path / "dataset" / "compiled_neutronics_data.h5"

            self.assertTrue(report_path.exists())
            self.assertTrue(compiled_hdf5.exists())

            with report_path.open("r", encoding="utf-8") as stream:
                report = json.load(stream)
            self.assertEqual(report["requested_iterations"], 5)
            self.assertEqual(report["extracted_iterations"], 5)

            run_dir = tmp_path / "runs" / "iter_0001"
            with (run_dir / "run_metadata.json").open("r", encoding="utf-8") as stream:
                run_metadata = json.load(stream)
            self.assertTrue(run_metadata["used_fallback_dagmc"])

            with (run_dir / "openmc_status.json").open("r", encoding="utf-8") as stream:
                openmc_status = json.load(stream)
            self.assertTrue(openmc_status["used_fallback_statepoint"])
