fmt:
	uv run --group dev ruff format .
	uv run --group dev ruff check --fix .

lint:
	uv run --group dev ruff format --check .
	uv run --group dev ruff check .

test:
	uv run --group dev pytest

.PHONY: fmt lint test
