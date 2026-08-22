.PHONY: install sync test typecheck build dev serve e2e migrate check owner keys

install:
	uv sync --project backend --all-groups
	pnpm --dir frontend install

sync: install migrate

test:
	uv run --directory backend pytest -q
	pnpm --dir frontend test

typecheck:
	pnpm --dir frontend typecheck

build:
	pnpm --dir frontend build

dev:
	pnpm --dir frontend dev

serve: build
	uv run --directory backend uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000

owner:
	uv run --directory backend python -m app.cli create-owner --email $(EMAIL)

keys:
	uv run --directory backend python -m app.cli generate-keys

check: test typecheck build

e2e:
	pnpm --dir frontend e2e

migrate:
	uv run --directory backend alembic upgrade head
