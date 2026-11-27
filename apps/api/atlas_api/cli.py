"""Command-line administration: ``atlas <command>``."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from shared.crypto import generate_fernet_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas", description="ATLAS OSINT administration")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    cu = sub.add_parser("create-user", help="create a user")
    cu.add_argument("email")
    cu.add_argument("--role", default="analyst", choices=["admin", "analyst", "viewer", "auditor"])
    rp = sub.add_parser("reset-password", help="set a new password for a user and clear any lockout")
    rp.add_argument("email")
    rp.add_argument("--stdin", action="store_true", help="read the new password from standard input")
    sub.add_parser("retention", help="purge investigations past their retention date")
    sub.add_parser("generate-keys", help="print fresh secret/encryption/hash keys for .env")
    sub.add_parser("sources", help="list registered source adapters as JSON")
    args = parser.parse_args(argv)

    if args.cmd == "generate-keys":
        import secrets

        print(f"ATLAS_SECRET_KEY={secrets.token_urlsafe(48)}")
        print(f"ATLAS_ENCRYPTION_KEY={generate_fernet_key()}")
        print(f"ATLAS_HASH_KEY={secrets.token_urlsafe(48)}")
        return 0
    if args.cmd == "sources":
        from integrations.sources.registry import get_registry

        print(json.dumps([a.meta.model_dump(mode="json") for a in get_registry().all()], indent=2))
        return 0

    from atlas_api.db import get_sessionmaker
    from atlas_api.main import run_migrations

    if args.cmd == "migrate":
        run_migrations()
        print("migrations applied")
        return 0
    if args.cmd == "create-user":
        from atlas_api.models import User
        from atlas_api.security import hash_password, validate_password_strength

        password = getpass.getpass("Password: ")
        try:
            validate_password_strength(password)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        with get_sessionmaker()() as db:
            db.add(User(email=args.email.lower(), password_hash=hash_password(password), role=args.role))
            db.commit()
        print(f"created {args.role} {args.email}")
        return 0
    if args.cmd == "reset-password":
        from sqlalchemy import select

        from atlas_api.audit import audit
        from atlas_api.models import User
        from atlas_api.security import hash_password, validate_password_strength

        if args.stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("New password: ")
            if getpass.getpass("Repeat: ") != password:
                print("error: passwords do not match", file=sys.stderr)
                return 1
        try:
            validate_password_strength(password)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        with get_sessionmaker()() as db:
            user = db.scalar(select(User).where(User.email == args.email.lower()))
            if user is None:
                print(f"error: no user {args.email}", file=sys.stderr)
                return 1
            user.password_hash = hash_password(password)
            user.failed_logins = 0
            user.locked_until = None
            audit(db, actor_id=None, action="user.password_reset_cli", target_type="user", target_id=user.id)
            db.commit()
        print(f"password updated for {args.email}; lockout cleared")
        return 0
    if args.cmd == "retention":
        from atlas_api.services.investigations import purge_expired

        with get_sessionmaker()() as db:
            print(f"removed {purge_expired(db)} investigations")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
