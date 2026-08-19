"""Local operator commands.

    uv run --directory backend python -m app.cli create-owner --email you@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import secrets
import sys
from getpass import getpass

from app.config import get_settings
from app.db import create_database
from app.services import auth as auth_service


async def _create_owner(email: str, password: str) -> str:
    settings = get_settings()
    database = create_database(settings)
    try:
        async with database.session() as session:
            owner = await auth_service.create_owner(session, email, password)
            await session.commit()
            return owner.email
    finally:
        await database.dispose()


def _prompt_password() -> str:
    first = getpass("Owner password: ")
    second = getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    if len(first) < auth_service.MINIMUM_PASSWORD_LENGTH:
        raise SystemExit(
            f"Password must be at least {auth_service.MINIMUM_PASSWORD_LENGTH} "
            "characters."
        )
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-owner", help="Create the single owner account")
    create.add_argument("--email", required=True)
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from stdin instead of prompting (for scripts).",
    )

    commands.add_parser("generate-keys", help="Print fresh local secrets")

    args = parser.parse_args(argv)

    if args.command == "generate-keys":
        print(f"APPLICATION_SECRET={secrets.token_urlsafe(48)}")
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        print(f"TOKEN_ENCRYPTION_KEY={key}")
        return 0

    if getattr(args, "password_stdin", False):
        password = sys.stdin.readline().rstrip("\n")
        if len(password) < auth_service.MINIMUM_PASSWORD_LENGTH:
            print(
                f"Password must be at least {auth_service.MINIMUM_PASSWORD_LENGTH} "
                "characters.",
                file=sys.stderr,
            )
            return 1
    else:
        password = _prompt_password()
    try:
        email = asyncio.run(_create_owner(args.email, password))
    except auth_service.OwnerAlreadyExistsError:
        print("An owner account already exists; refusing to create a second.", file=sys.stderr)
        return 1
    except auth_service.WeakPasswordError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Created owner {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
