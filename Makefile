.PHONY: test check build zipapp artifacts smoke

test:
	python3 scripts/run_tests.py

check: test smoke
	python3 -m compileall -q src tests scripts
	python3 scripts/leak_guard.py
	python3 scripts/validate_distribution.py

build:
	python3 scripts/build_wheel.py

zipapp:
	python3 scripts/build_zipapp.py

artifacts: zipapp build
	python3 scripts/verify_artifacts.py

smoke: artifacts
	python3 dist/codex-storage-doctor.pyz --version
	PYTHONPATH=src python3 -m codex_storage_doctor --help >/dev/null
