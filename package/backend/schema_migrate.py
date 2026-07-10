#!/usr/bin/env python3
"""One-shot production schema migration entrypoint."""

import argparse

from app.schema import upgrade_database_schema, verify_database_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the GankAIGC PostgreSQL schema")
    parser.add_argument(
        "action",
        choices=("upgrade", "verify"),
        nargs="?",
        default="upgrade",
    )
    parser.add_argument("--lock-timeout", type=int, default=300)
    args = parser.parse_args()

    if args.action == "verify":
        revision = verify_database_schema()
        print(f"Schema verification passed: {revision}")
        return

    revision = upgrade_database_schema(lock_timeout_seconds=args.lock_timeout)
    print(f"Schema migration completed: {revision}")


if __name__ == "__main__":
    main()
