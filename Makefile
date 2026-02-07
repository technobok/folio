.PHONY: help sync install init-db run rundev check clean config-list config-set config-export

SHELL := /bin/bash
VENV_DIR := $(or $(VIRTUAL_ENV),.venv)
ADMIN := $(VENV_DIR)/bin/folio-admin
WEB := $(VENV_DIR)/bin/folio-web
RUFF := $(VENV_DIR)/bin/ruff
TY := $(VENV_DIR)/bin/ty

help:
	@echo "Folio - Document Management System"
	@echo "-----------------------------------"
	@echo "sync     - Sync dependencies with uv (creates venv if needed)"
	@echo "install  - Alias for sync"
	@echo "init-db  - Create a blank database"
	@echo "run      - Run server via gunicorn (0.0.0.0:5001)"
	@echo "rundev   - Run Flask dev server (DEV_HOST:DEV_PORT, debug=True)"
	@echo "config-list  - Show all config settings"
	@echo "config-set KEY=key VAL=value  - Set a config value"
	@echo "config-export FILE=path  - Export all settings as a shell script"
	@echo "check    - Run ruff and ty for code quality"
	@echo "clean    - Remove temporary files and database"
	@echo ""
	@echo "Database: instance/folio.sqlite3 (default)"
	@echo "Set FOLIO_DB to override, e.g.:"
	@echo "  export FOLIO_DB=/data/folio.sqlite3"

sync:
	@uv sync --extra dev

install: sync

init-db:
	@$(ADMIN) init-db

run:
	@$(WEB)

rundev:
	@$(WEB) --dev

config-list:
	@$(ADMIN) config list

config-set:
	@$(ADMIN) config set $(KEY) $(VAL)

config-export:
	@$(ADMIN) config export $(or $(FILE),$(file))

check:
	@$(RUFF) format src tests
	@$(RUFF) check src tests --fix
	@if [ -z "$$VIRTUAL_ENV" ]; then unset VIRTUAL_ENV; fi; $(TY) check src

clean:
	@find . -type f -name '*.py[co]' -delete
	@find . -type d -name '__pycache__' -delete
	@rm -f instance/folio.sqlite3
