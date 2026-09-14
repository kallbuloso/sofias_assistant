"""CLI for administering local Sofia's Assistant secrets.

Never prints, logs, or accepts a secret value as a CLI argument. Use:

    uv run python -m sofias_assistant.secrets set <ref>
    uv run python -m sofias_assistant.secrets exists <ref>
    uv run python -m sofias_assistant.secrets delete <ref>

`set` prompts interactively via `getpass.getpass`, so the value never appears
in the command line, the terminal echo, or shell history. There is
intentionally no `show`/`get`/`reveal` command.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sofias_assistant.secrets",
        description="Administer local Sofia's Assistant secrets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser(
        "set", help="Store a secret value; prompts interactively, never echoed."
    )
    set_parser.add_argument(
        "ref", help="SecretRef identifier, e.g. integrations/sofias-memory/api-key"
    )

    exists_parser = subparsers.add_parser(
        "exists", help="Check whether a secret is stored, without revealing it."
    )
    exists_parser.add_argument("ref")

    delete_parser = subparsers.add_parser("delete", help="Delete a stored secret.")
    delete_parser.add_argument("ref")

    return parser


def main(
    argv: list[str] | None = None,
    *,
    store_factory: Callable[[], SecretStore] = WindowsCredentialStore,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    """Run the Secret CLI; returns a process exit code, never a secret value."""

    args = _build_parser().parse_args(argv)
    ref = SecretRef(args.ref)
    service = SecretService(store_factory())

    if args.command == "set":
        value = prompt(f"Value for {ref.identifier}: ")
        if not value:
            print("Aborted: empty value was not stored.", file=sys.stderr)
            return 1
        service.set(ref, SecretValue(value))
        print(f"Stored secret for {ref.identifier}.")
        return 0

    if args.command == "exists":
        found = service.get(ref) is not None
        print("yes" if found else "no")
        return 0 if found else 1

    if args.command == "delete":
        deleted = service.delete(ref)
        print("deleted" if deleted else "not found")
        return 0 if deleted else 1

    parser = _build_parser()
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse.error() always raises SystemExit


if __name__ == "__main__":
    raise SystemExit(main())
