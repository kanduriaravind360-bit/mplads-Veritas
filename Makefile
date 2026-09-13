# MPLADS Sentinel: common tasks.
#
# On Windows the verified path is demo.ps1 (make is not installed on the build
# machine). These targets run the same steps from a POSIX shell (Git Bash, WSL,
# Linux, macOS) and were written to match demo.ps1 step for step.

ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
else
PY ?= .venv/bin/python
endif
NPM ?= npm
API_PORT ?= 8000
WEB_PORT ?= 4173

.PHONY: help setup pipeline planted load seed web api demo test e2e deck digest clean-db

help:
	@echo "make setup     install Python and frontend dependencies"
	@echo "make pipeline  run the ML pipeline (python -m ml.train)"
	@echo "make load      load pipeline outputs into the app database"
	@echo "make seed      learning seeds and the guaranteed demo scenarios"
	@echo "make demo      everything above if needed, then API + dashboard"
	@echo "make test      ruff, pytest, typecheck and unit tests"
	@echo "make e2e       Playwright end-to-end tests (writes screenshots)"
	@echo "make deck      build the PowerPoint deck"

setup:
	uv venv --python 3.12
	uv pip install --python $(PY) -e ".[dev]"
	$(NPM) --prefix frontend ci

pipeline:
	test -f data/processed/scored_works.parquet || $(PY) -m ml.train

planted:
	test -f data/processed/planted_scored.parquet || $(PY) -m ml.planted

load: pipeline
	test -f data/app/sentinel.db || $(PY) -m backend.app.loader

seed: load
	if test -f data/processed/planted_scored.parquet; then $(PY) -m backend.app.learning_seed; fi
	$(PY) -m backend.app.demo_seed --reset

web:
	test -d frontend/node_modules || $(NPM) --prefix frontend ci
	test -f frontend/dist/index.html || $(NPM) --prefix frontend run build

api:
	PRESENTATION_MODE=1 SCHEDULER_ENABLED=0 $(PY) -m uvicorn backend.app.main:app --host 127.0.0.1 --port $(API_PORT)

demo: seed web
	@echo "Dashboard: http://127.0.0.1:$(WEB_PORT)  (demo password: demo123)"
	PRESENTATION_MODE=1 SCHEDULER_ENABLED=0 $(PY) -m uvicorn backend.app.main:app --host 127.0.0.1 --port $(API_PORT) & \
	API_PID=$$!; trap "kill $$API_PID" EXIT INT TERM; \
	SENTINEL_API=http://127.0.0.1:$(API_PORT) SENTINEL_PREVIEW_PORT=$(WEB_PORT) $(NPM) --prefix frontend run preview

test:
	$(PY) -m ruff check .
	$(PY) -m pytest
	$(NPM) --prefix frontend run typecheck
	$(NPM) --prefix frontend test

e2e:
	$(NPM) --prefix frontend run e2e

deck:
	$(PY) presentation/build_deck.py

digest:
	$(PY) -m backend.app.digest

clean-db:
	rm -f data/app/sentinel.db data/app/sentinel.db-wal data/app/sentinel.db-shm
