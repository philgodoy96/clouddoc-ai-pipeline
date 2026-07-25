.PHONY: install format format-check lint test test-cov check clean

PYTHON := python

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check . --fix

format-check:
	$(PYTHON) -m ruff format . --check

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest

test-cov:
	$(PYTHON) -m pytest --cov=clouddoc --cov-report=term-missing

check: format-check lint test

clean:
	$(PYTHON) -c "import pathlib, shutil; targets = ['.pytest_cache', '.ruff_cache', 'build', 'dist', 'htmlcov']; [shutil.rmtree(path, ignore_errors=True) for path in targets]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').rglob('__pycache__')]"
