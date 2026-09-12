.PHONY: test test-comics up down setup deploy

test:
	cd apps/resto-core && pip install -q -r requirements.txt pytest && pytest -q
	$(MAKE) test-comics

test-comics:
	python3 scripts/tests/test_comics_visibility.py

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
