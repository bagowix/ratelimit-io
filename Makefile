
pre-commit:
	pre-commit run --all-files


pytest:
	pytest --failed-first -vvv --cov=ratelimit_io --cov-report=json


mypy:
	mypy .
