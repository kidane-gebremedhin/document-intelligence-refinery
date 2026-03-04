.PHONY: setup test lint run

setup:
	uv sync

test:
	uv run pytest -q

run:
	uv run python -m src.main