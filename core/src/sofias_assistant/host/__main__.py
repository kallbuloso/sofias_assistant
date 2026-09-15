"""`python -m sofias_assistant.host` entry point for the production Core host."""

from sofias_assistant.host.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
