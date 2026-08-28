fmt:
	uv run --group dev black --line-length 120 .
	uv run --group dev isort . --treat-comment-as-code "# %%"

