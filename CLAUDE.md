# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

**Implemented (U1–U5), pending the manual live routing smoke.** The package, tests and lockfile exist on branch `feat/notebokki-mcp-server`. The U3 live gate passed on 2026-10-17: a hand-built storage-state payload authenticates and reads a real notebook (finding recorded in the plan's Open Questions). The remaining open gate is the manual smoke in the Commands section.

Layout: `src/notebokki/` — `config.py` (all paths), `registry.py` (allowlist, exact match), `notebooklm.py` (the only library importer; `Gateway`, error classification, title map, log guard), `errors.py` (the four branches), `setup.py` (session ingest and per-topic validation), `server.py` (the three tools and the provenance envelope), `__main__.py` (`notebokki setup|serve`).

User-facing docs: `README.md` (overview), `docs/SETUP.md` (install, session capture, wiring into Claude), and `CLAUDE.BUSINESS-RULE.md` (a snippet other projects import with `@` so Claude consults notebokki for business rules). Keep them in step with the code.

`docs/plans/2026-10-11-001-feat-notebokki-notebooklm-mcp-plan.md` is the source of truth for what notebokki is and how it is built. It is a compound-engineering unified plan at `artifact_readiness: implementation-ready`. Read it by heading (`## Goal Capsule`, `## Product Contract`, `## Planning Contract`, `## Implementation Units`, `## Verification Contract`, `## Definition of Done`) rather than end to end.

## What notebokki is

A read-only MCP server (stdio) that exposes a developer's NotebookLM notebooks to Claude Code and Claude Desktop as a question-answering source, so a business rule can be fetched mid-task instead of looked up in a browser and relayed by hand.

Three tools: list topics, ask (synthesized answer), search (verbatim source passages). A hand-authored JSON registry maps short topic names to notebook URLs with descriptions; Claude reads the descriptions and chooses the topic itself.

## Commands

These are the plan's Verification Contract and all work today.

```bash
uv sync --locked                                   # install exactly the locked artifacts; fails if uv.lock is stale
uv run pytest                                      # full suite; must pass with no network and no credentials
uv run ruff check                                  # lint
uv run pytest tests/test_registry.py               # one test file
uv run pytest tests/test_registry.py::test_name    # one test
uv run pytest tests/test_server.py -k handshake    # the stdio MCP handshake gate
uv run pytest tests/test_library_surface.py        # pins notebooklm-py's surface; fails loudly on a bad upgrade
```

The suite must run with no credentials present. A test that needs a live NotebookLM session has broken the faked-boundary contract.

The only manual gate is a live routing smoke: `notebokki setup`, then pose a real business-rule task **without** naming a topic or a mode, and check that Claude picks both unaided. A wrong pick means a registry description or a tool description needs rewriting, not that the code failed.

## Architectural invariants

These are the load-bearing constraints. Breaking one silently defeats a decision the owner made deliberately.

- **One library importer.** `notebooklm-py` is reachable from exactly one module. Everything else talks to that seam. A second importer loses the containment that makes a later swap cheap — asserted by test, not by review.
- **The registry is the sole allowlist.** Only notebooks named in it are reachable. Notebokki never enumerates the account's notebooks, for the developer or for Claude. No discovery tool, no setup-time listing.
- **Exact topic match or loud failure.** An unregistered topic is rejected with the full list of valid topics. No fuzzy matching anywhere — for business rules, an error beats a confident answer from the wrong notebook, and the error doubles as topic discovery.
- **Four error branches, not collapsible:** unknown topic, dead session, notebook unreachable, upstream-or-throttled. Each sends the developer somewhere different; conflating any two sends them to a fix that cannot work.
- **Results carry a provenance envelope** that echoes the resolved topic and its description. This exposes misroutes (a *registered but wrong* notebook would otherwise answer confidently) and labels notebook text as untrusted content that must never be followed as an instruction. A provenance label is not synthesis, so it does not violate the pass-through requirement.
- **Pass through, never supplement.** NotebookLM's output is returned as-is. No second model, no general knowledge, no summarizing wrapper over verbatim passages.
- **Read-only as to notebook content.** No tool adds, edits, or removes a source, notebook, or structure. Asking *does* record a chat turn — the same write the web UI performs — so the guarantee is about content, not about issuing no writes at all.

## Hard-won facts — do not re-derive

Each of these was established by verification in-repo. Re-discovering them costs a cycle.

- The library's import name is **`notebooklm`**, not `notebooklm_py`.
- `mcp` 2.x renamed `FastMCP` to `MCPServer`. Every prior-art server cited in the plan's Sources section is 1.x-era, so their import shapes do not transfer even though their tool surface does.
- **`chat.ask` without a `conversation_id` extends the notebook's single existing chat thread.** True per-call statelessness would require `delete_conversation(...)`, which destroys the developer's own chat history. The owner chose shared threading; notebokki never creates, deletes, or rotates a thread.
- `sources.search` never touches conversation state, so the verbatim path is already stateless.
- `Source.title` and `ChatReference.cited_text` are both nullable. Handle null, not just missing.
- Every library call is a coroutine and the client is a loop-bound async context manager — hence `pytest-asyncio` and a single client opened at server start.
- **`chmod 600` on a `/mnt/c` DrvFs path returns exit 0 and leaves the mode at 777.** Gating on chmod's return value reports success while leaving a full-account credential world-readable. `stat` after writing and require exactly `0600`.
- **`git check-ignore` exits 128 for any path outside the working tree.** It cannot test a session path living outside the repo, and a test written that way would force the credential *into* the repo. Assert the resolved path is outside the worktree instead.
- The session reaches the library through an **explicit storage path only**. `NOTEBOOKLM_AUTH_JSON` was rejected: an MCP server's environment is authored in the launcher's config file, which is routinely committed.
- The library hard-requires only `SID` and `__Secure-1PSIDTS`, and merely *warns* when the secondary binding is absent. Setup validates more strictly on purpose.
- The session payload is a Playwright **storage-state JSON** object, not a DevTools cookie dump.
- A storage-state payload hand-built from a browser request's `Cookie` header (every cookie on `.google.com`, `expires: -1`, `origins: []`) authenticates. Verified live, not just assumed.
- `server.call_tool(...)` in-process raises `ToolError` for a tool failure; only the protocol layer turns it into `is_error`. Tests catch it. `CallToolResult` uses `is_error`, not `isError`.
- If `uv sync` ran before `src/notebokki/` had files, the editable install is empty: `uv sync --locked --reinstall-package notebokki`.
- The library already locks per conversation and retries throttled calls internally. A global request-serialization queue was considered and dropped.

## Working conventions

- **Session-settled decisions are closed.** Entries in the plan annotated `(session-settled: user-directed — chosen over X: reason)` were chosen by the owner with the tradeoff in view. Augment them with evidence; do not reopen them. If you find evidence one cannot work, surface it — do not quietly route around it.
- **Stable IDs.** R (requirements), A (actors), F (flows), AE (acceptance examples), KTD (technical decisions), U (units). Never renumber to close a gap — `KTD6` is intentionally absent because that decision was dropped. New entries take the next unused number.
- **One owner per rule.** A rule is stated in full on exactly one entry; everything else cites its ID. Requirements win on product behavior, KTDs win on implementation mechanism within the requirements they cite, units override neither.
- **Repo-relative paths** in all plan and doc content.
- The credential never lives in the repo. Config goes under `~/.config/notebokki/` (honoring `XDG_CONFIG_HOME`), session file in its own directory at mode `0600`.
- `.compound-engineering/config.local.yaml` is gitignored; `config.local.example.yaml` is committed.

## Build order (historical)

U1 → (U2, U3 independently) → (U4, U5). U3 gated the rest: the library surface test and a live probe of a hand-captured session both had to pass before U4 or U5 was written. Both passed. If a library bump breaks `tests/test_library_surface.py`, stop and surface it rather than adapting around it.
