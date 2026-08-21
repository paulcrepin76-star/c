.PHONY: test up down

test:
	cd apps/resto-core && pip install -q -r requirements.txt pytest && pytest -q

up:
	docker compose up -d --build

down:
	docker compose down
