.PHONY: install bootstrap test lint typecheck preflight verify demo serve doctor package

install:
	python -m pip install -e '.[dev]'

bootstrap:
	./scripts/bootstrap_codex.sh

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

preflight:
	./scripts/preflight.sh

verify:
	./scripts/verify_all.sh

demo:
	hanalpha demo --cycles 5

serve:
	hanalpha serve

doctor:
	hanalpha doctor

package:
	cd .. && zip -r han-alpha.zip han-alpha -x 'han-alpha/.venv/*' 'han-alpha/.state/*'
