.PHONY: install lint format test smoke check

install:
	python -m pip install --upgrade pip
	python -m pip install -r requirements-dev.txt

lint:
	ruff check .

format:
	ruff check --fix .
	ruff format .

test:
	PYTHONPATH=. pytest -q

smoke:
	PYTHONPATH=. python -m unittest tests.test_smoke -v

check: lint test smoke
