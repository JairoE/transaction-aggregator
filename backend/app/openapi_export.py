"""Print the OpenAPI document so the frontend can regenerate its types.

    pnpm --dir frontend generate:api
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    os.environ.setdefault("ENVIRONMENT", "demo")
    os.environ.setdefault("APPLICATION_SECRET", "s" * 32)
    os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "k" * 43)
    os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    os.environ.setdefault("PLAID_CLIENT_ID", "openapi-export")
    os.environ.setdefault("PLAID_SECRET", "openapi-export")

    from app.main import create_app

    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
