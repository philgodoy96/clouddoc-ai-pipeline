.PHONY: install format format-check lint test test-cov \
        lambda-lock lambda-package lambda-package-check lambda-clean \
        check clean

PYTHON := python
LAMBDA_REQUIREMENTS_INPUT := requirements/lambda.in
LAMBDA_REQUIREMENTS_LOCK := requirements/lambda.lock.txt
LAMBDA_ARTIFACT := artifacts/lambda/clouddoc-app.zip
LAMBDA_CHECKSUM := artifacts/lambda/clouddoc-app.sha256

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

lambda-lock:
	$(PYTHON) -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --no-allow-unsafe --no-emit-index-url --no-emit-trusted-host --newline=lf --upgrade --output-file=$(LAMBDA_REQUIREMENTS_LOCK) $(LAMBDA_REQUIREMENTS_INPUT)

lambda-package:
	$(PYTHON) scripts/build_lambda_package.py

lambda-package-check: lambda-package
	$(PYTHON) -c "import hashlib, pathlib; artifact = pathlib.Path('$(LAMBDA_ARTIFACT)'); checksum = pathlib.Path('$(LAMBDA_CHECKSUM)'); expected = checksum.read_text(encoding='utf-8').split()[0]; actual = hashlib.file_digest(artifact.open('rb'), 'sha256').hexdigest(); assert actual == expected, f'Checksum mismatch: {actual} != {expected}'; print(f'Lambda package checksum verified: {actual}')"

lambda-clean:
	$(PYTHON) -c "import pathlib, shutil; targets = [pathlib.Path('.lambda-build'), pathlib.Path('artifacts/lambda')]; [shutil.rmtree(path, ignore_errors=True) for path in targets]"

check: format-check lint test

clean: lambda-clean
	$(PYTHON) -c "import pathlib, shutil; targets = ['.pytest_cache', '.ruff_cache', 'build', 'dist', 'htmlcov']; [shutil.rmtree(path, ignore_errors=True) for path in targets]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').rglob('__pycache__')]"
