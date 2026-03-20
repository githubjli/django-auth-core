PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
MANAGE := $(VENV_PYTHON) backend/manage.py
APP_HOST ?= 127.0.0.1
APP_PORT ?= 8001

.PHONY: venv install migrate run test check

venv:
	$(PYTHON) -m venv $(VENV_DIR)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -r requirements.txt

migrate:
	$(MANAGE) migrate

run:
	$(MANAGE) runserver $(APP_HOST):$(APP_PORT)

test:
	$(MANAGE) test

check:
	$(MANAGE) check
