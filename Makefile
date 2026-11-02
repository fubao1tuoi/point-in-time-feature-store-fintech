.PHONY: install test lint format check

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

format:
	python -m ruff format .

check: lint test

