# notebokki

A read-only MCP server (stdio) that exposes your registered NotebookLM notebooks to Claude Code and
Claude Desktop as a question-answering source, so a business rule can be fetched mid-task instead of
looked up in a browser.

Three tools: `list_topics`, `ask` (NotebookLM's synthesized answer) and `search` (verbatim source
passages). Notebokki never adds, edits or removes a notebook, source or structure. Asking records a
chat turn on the notebook's single chat thread, the same write the web UI performs.

## Install

```bash
uv sync --locked
```

## Registry

Create `~/.config/notebokki/registry.json` (honors `XDG_CONFIG_HOME`). It is the only allowlist:
notebokki never lists your notebooks. Write each description so an agent can choose a topic from it.

```json
{
  "billing": {
    "url": "https://notebooklm.google.com/notebook/<id>",
    "description": "Invoice, refund and proration rules for the billing service"
  }
}
```

An unregistered topic is rejected with the full list of valid topics. There is no fuzzy matching.

## Session

`notebokki setup` ingests a Playwright storage-state JSON (a `cookies` array plus `origins`) from piped
stdin or `--from-file`. It never accepts the payload as an argument or a prompt. It must contain `SID`,
`__Secure-1PSIDTS`, and either `OSID` or all of `APISID`, `SAPISID`, `LSID`.

```bash
uv run notebokki setup --from-file ~/state.json && rm ~/state.json
```

The session is written to `~/.config/notebokki/session/storage_state.json` at mode `0600`, outside any
repository, and setup then validates every registry entry with one call per topic.

**The session file grants full access to your Google account while it is valid.** Treat it as a
password. Revoking it is a Google-side action (sign out of that session). Do not use a path under
`/mnt/c`: DrvFs ignores permissions and setup refuses it.

## Host configuration

```json
{
  "mcpServers": {
    "notebokki": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/notebokki", "notebokki", "serve"]
    }
  }
}
```

Put no credential in this file. The session is reached through the storage path only.

## Development

```bash
uv sync --locked
uv run pytest        # no network, no credentials
uv run ruff check
```

See `docs/plans/` for the plan and `CLAUDE.md` for the invariants.
