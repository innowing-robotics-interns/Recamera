.PHONY: help setup test test-all lint fmt integration check clean

help:
	@echo "setup       create .venv and install dependencies (uv sync --extra test)"
	@echo "test        run unit tests (no camera needed)"
	@echo "lint        ruff check"
	@echo "fmt         ruff format + fix"
	@echo "check       lint + unit tests"
	@echo "integration run tests against a real camera (RECAMERA_INTEGRATION=1)"
	@echo "clean       remove caches and build artefacts"

setup:
	uv sync --extra test

test:
	env -u PYTHONPATH -u PYTHONHOME uv run --extra test pytest

lint:
	uvx ruff check .

fmt:
	uvx ruff format .
	uvx ruff check --fix .

check: lint test

integration:
	env -u PYTHONPATH -u PYTHONHOME RECAMERA_INTEGRATION=1 uv run --extra test pytest tests/test_integration_camera.py -v

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
