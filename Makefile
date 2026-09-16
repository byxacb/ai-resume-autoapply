SHELL := /bin/bash
PYTHON := python3
PIP := pip
UVICORN := uvicorn
REDIS_URL ?= redis://localhost:6379/0

.PHONY: help install install-dev dev test lint format clean up down logs

help:
	@echo "AI Resume AutoApply Makefile"
	@echo ""
	@echo "  make install      Install production dependencies"
	@echo "  make install-dev  Install development dependencies"
	@echo "  make dev          Start local development server (reload)"
	@echo "  make test         Run pytest suite"
	@echo "  make lint         Run ruff + mypy"
	@echo "  make up           Start docker-compose (prod)"
	@echo "  make down         Stop docker-compose"
	@echo "  make logs         Tail orchestrator logs"

install:
	$(PIP) install -r orchestrator/requirements.txt

install-dev:
	$(PIP) install -r orchestrator/requirements.txt
	$(PIP) install pytest pytest-asyncio ruff mypy websocket-client

dev:
	REDIS_URL=$(REDIS_URL) $(UVICORN) web.server:app --host 0.0.0.0 --port 8080 --reload

test:
	pytest -q

lint:
	ruff check orchestrator web tests || true
	mypy orchestrator || true

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f orchestrator-api

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + || true
	find . -type f -name '*.pyc' -delete || true
	rm -rf .venv uploads/*.txt || true
