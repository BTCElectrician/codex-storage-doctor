.PHONY: test check build zipapp smoke

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: test smoke
	python3 -m compileall -q src tests scripts
	python3 scripts/leak_guard.py
	python3 scripts/validate_distribution.py

build:
	python3 -m pip wheel . --no-deps --no-build-isolation -w dist

zipapp:
	python3 scripts/build_zipapp.py

smoke: zipapp
	python3 dist/codex-storage-doctor.pyz --version
	PYTHONPATH=src python3 -m codex_storage_doctor --help >/dev/null
