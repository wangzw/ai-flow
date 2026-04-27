.PHONY: test cov lint format

test:
	pytest

cov:
	pytest --cov=sw --cov-report=term-missing

lint:
	ruff check src tests

format:
	ruff format src tests
