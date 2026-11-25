.PHONY: help install seed reset test verify demo api web lint clean

PYTHON ?= python
AS_OF ?= 2026-11-25

help:
	@echo "WEMA - commandes disponibles"
	@echo "  make install  installe les dependances Python et web"
	@echo "  make seed     charge le jeu de demonstration (AS_OF=$(AS_OF))"
	@echo "  make reset    reinitialise la base et les fichiers generes"
	@echo "  make test     execute les tests (unittest, sans reseau)"
	@echo "  make verify   verifie la chaine d'audit et les hash PDF"
	@echo "  make demo     lance l'API en mode AI_BACKEND=demo"
	@echo "  make api      lance l'API"
	@echo "  make web      lance le frontend Vite"

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt
	cd web && npm install

seed:
	$(PYTHON) -m seed --reset --as-of $(AS_OF)

reset:
	$(PYTHON) -m seed --reset --as-of $(AS_OF) --force

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

verify:
	$(PYTHON) -m cli verify

demo:
	AI_BACKEND=demo $(PYTHON) -m api.app

api:
	$(PYTHON) -m api.app

web:
	cd web && npm run dev

lint:
	$(PYTHON) -m compileall -q config.py db.py schema.py seed.py cli.py api domain adapters worker tests

clean:
	$(PYTHON) -m cli clean
