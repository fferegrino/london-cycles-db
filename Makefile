fmt:
	black --line-length 120 .
	isort . --treat-comment-as-code "# %%"
