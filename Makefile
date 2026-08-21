.PHONY: test up down setup deploy

test:
	cd apps/resto-core && pip install -q -r requirements.txt pytest && pytest -q

setup:
	chmod +x scripts/*.sh
	./scripts/setup.sh

up:
	docker compose up -d --build

down:
	docker compose down

deploy:
	chmod +x scripts/*.sh
	./scripts/deploy-unraid.sh $(UNRAID_SSH)
