import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notebokki", description="Read-only MCP server over registered NotebookLM notebooks."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="capture a NotebookLM session and validate the registry")
    setup.add_argument(
        "--from-file", help="read the storage-state JSON from this file (else stdin)"
    )
    setup.add_argument("extra", nargs="*", help=argparse.SUPPRESS)  # rejects argv payloads
    sub.add_parser("serve", help="run the MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        from .setup import main as setup_main

        return setup_main(args.from_file, args.extra)
    if args.command == "serve":
        from .server import serve

        return serve()
    print(f"notebokki {args.command}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
