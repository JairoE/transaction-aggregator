.PHONY: install test typecheck build dev serve e2e migrate

install:
	uv sync --project backend --all-groups
	pnpm --dir frontend install

test:
	uv run --directory backend pytest -q
	pnpm --dir frontend test

typecheck:
	pnpm --dir frontend typecheck

build:
	pnpm --dir frontend build

dev:
	pnpm --dir frontend dev

serve:
	uv run --directory backend uvicorn app.main:app --host 127.0.0.1 --port 8000

e2e:
	pnpm --dir frontend e2e

migrate:
	uv run --directory backend alembic upgrade head
