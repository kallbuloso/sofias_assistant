"""Command-line entry point for Sofia's Assistant."""

from importlib.metadata import version


def main() -> int:
    """Print the installed application identity and version."""
    print(f"Sofia's Assistant {version('sofias-assistant')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
