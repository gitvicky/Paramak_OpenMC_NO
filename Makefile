PYTHON ?= $(if $(wildcard .venv/bin/python),./.venv/bin/python,python3)
CONFIG ?= config.yaml

.PHONY: all doe cad openmc extract smoke test-smoke clean

all: doe cad openmc extract

doe:
	$(PYTHON) src/01_generate_doe.py --config $(CONFIG) --write-parquet --overwrite

cad:
	$(PYTHON) src/02_build_cad.py --config $(CONFIG) --resume

openmc:
	$(PYTHON) src/03_run_openmc.py --config $(CONFIG) --resume

extract:
	$(PYTHON) src/04_extract_data.py --config $(CONFIG)

smoke:
	$(MAKE) all CONFIG=configs/config.smoke.yaml

test-smoke:
	$(PYTHON) -m unittest tests.test_smoke

clean:
	rm -rf runs/iter_* dataset/doe_parameters.csv dataset/doe_parameters.parquet dataset/compiled_neutronics_data.h5 dataset/extraction_report.json
