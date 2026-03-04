# CLI entrypoint for Document Intelligence Refinery.
# Run: uv run python -m src.main --pdf <path>

from __future__ import annotations

import argparse
import logging
import sys

from src.agents import run_triage


def main() -> int:
    parser = argparse.ArgumentParser(description="Document Intelligence Refinery — triage a PDF")
    parser.add_argument("--pdf", type=str, required=True, help="Path to PDF file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    try:
        profile = run_triage(args.pdf)
        print(profile.to_profile_json())
        return 0
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:
        logging.exception("triage failed")
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
