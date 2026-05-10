# Convenience wrappers for the local stack. Every target delegates to
# scripts/local/setup.sh — see that script for what each step does.
#
# Quickstart (first-time):
#   make all           # one-shot end-to-end
#
# Day-to-day:
#   make up            # start everything (assumes you've already done `all` once)
#   make down          # stop containers (preserves volumes)
#   make logs s=backend
#   make verify

SHELL := /bin/bash
SETUP := ./scripts/local/setup.sh

.PHONY: help all prereqs env build infra migrate seed services verify \
        up down restart clean logs ps shell-backend shell-pg-app shell-pg-nidp \
        ingest

help:
	@$(SETUP) help

prereqs:
	@$(SETUP) prereqs

env:
	@$(SETUP) env

build:
	@$(SETUP) build

infra:
	@$(SETUP) infra
	@$(SETUP) wait-infra

migrate:
	@$(SETUP) migrate

seed:
	@$(SETUP) seed

services:
	@$(SETUP) services

verify:
	@$(SETUP) verify

all:
	@$(SETUP) all

up: services
	@docker compose -f docker-compose.local.yml ps

down:
	@$(SETUP) down

restart: down up

clean:
	@$(SETUP) clean

# tail logs:  make logs s=backend
logs:
	@if [ -z "$(s)" ]; then echo "usage: make logs s=<backend|frontend|nidp-daas-api|nidp-query-api|postgres-app|postgres-nidp|mongodb|redis>"; exit 2; fi
	@$(SETUP) logs $(s)

ps:
	@docker compose -f docker-compose.local.yml ps

shell-backend:
	@docker exec -it nivesh-backend bash

shell-pg-app:
	@docker exec -it nivesh-pg-app psql -U nivesh -d nivesh_dev

shell-pg-nidp:
	@docker exec -it nivesh-pg-nidp psql -U postgres -d nidp

# Run any NIDP ingester on demand:
#   make ingest f=bhavcopy
#   make ingest f=amfi_nav
#   make ingest f=intelligence_layer
ingest:
	@if [ -z "$(f)" ]; then echo "usage: make ingest f=<feed_name>  e.g. make ingest f=bhavcopy"; exit 2; fi
	@docker compose -f docker-compose.local.yml exec backend python -m nidp.services.$(f)
