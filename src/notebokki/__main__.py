import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notebokki", description="Read-only MCP server over registered NotebookLM notebooks."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="capture a NotebookLM session and validate the registry")
    sub.add_parser("serve", help="run the MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Subcommand implementations land in later units (setup: U4, serve: U5).
    print(f"notebokki {args.command}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
