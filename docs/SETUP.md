# Setting up notebokki

This guide takes you from a fresh clone to Claude answering business-rule questions from your
NotebookLM notebooks. It takes about ten minutes. The only fiddly step is capturing a Google session.

**You need:** Python 3.10 or later, [`uv`](https://docs.astral.sh/uv/), Claude Code or Claude Desktop,
and a Google account that can open the notebooks you want to use.

---

## 1. Install

```bash
git clone <this repo> notebokki
cd notebokki
uv sync --locked
uv run notebokki --help      # lists: setup, serve
```

`--locked` installs exactly the pinned dependency set and fails if the lockfile is stale. That is
intentional: the dependencies sit in the path of your Google session.

---

## 2. Write the registry

The registry is the **only** list of notebooks notebokki can reach. It never lists your account's
notebooks, so you add each one by hand.

Create `~/.config/notebokki/registry.json`. (If `XDG_CONFIG_HOME` is set, use
`$XDG_CONFIG_HOME/notebokki/registry.json`.)

```json
{
  "asset-management": {
    "url": "https://notebooklm.google.com/notebook/<id>",
    "description": "Requirements for equipment lending and asset management: lending form, vehicle sublease contract, supplier master"
  }
}
```

- **Topic name:** short, lowercase, no spaces. Claude passes it back exactly. There is no fuzzy matching.
- **URL:** paste the notebook URL from your browser as it is. Notebooks on `notebooklm.google.com` and
  `notebook.google.com` both work. Query strings are ignored.
- **Description:** the most important field. Claude chooses a topic from this text alone. Say what the
  notebook covers and name its main documents. A vague description leads to wrong picks.

A missing file, an empty file, and invalid JSON each produce a different error message.

---

## 3. Capture a Google session

notebokki talks to NotebookLM with your own signed-in session. You capture it once, by hand.

The session must be a **Playwright storage-state JSON** object:

```json
{"cookies": [{"name": "SID", "value": "...", "domain": ".google.com", "path": "/"}], "origins": []}
```

It must contain `SID`, `__Secure-1PSIDTS`, **and** either `OSID` or all of `APISID`, `SAPISID`, `LSID`.
Setup rejects anything less, and names the missing cookies (never their values).

> **Warning.** This session grants full access to your Google account while it is valid. Treat it
> like a password. Do not paste it into chat, a ticket, or a commit.

### Easiest route: copy the `Cookie` header

The key cookies are `HttpOnly`, so `document.cookie` in the console cannot see them. The Network tab
can.

1. Open <https://notebooklm.google.com> in a browser where you are signed in.
2. Open DevTools, go to **Network**, and reload.
3. Click the main `notebooklm.google.com` document request, then **Headers**, then **Request Headers**.
4. Right-click the `cookie:` value and choose **Copy value**.
5. Paste it into a file on the Linux filesystem, for example `~/cookie-header.txt`. Use a file. A
   terminal truncates a very long pasted line.

> **WSL users:** keep the file on the Linux side (`/home/...`), not under `/mnt/c`. Windows drives
> ignore file permissions, so setup refuses them by design.

Convert the header into a storage-state file:

```bash
umask 077
python3 - <<'EOF'
import json, os, pathlib
raw = pathlib.Path(os.path.expanduser("~/cookie-header.txt")).read_text().strip()
if raw.lower().startswith("cookie:"):
    raw = raw[7:].strip()
cookies = []
for part in raw.split("; "):
    name, _, value = part.partition("=")
    if name:
        cookies.append({"name": name, "value": value, "domain": ".google.com", "path": "/",
                        "expires": -1, "httpOnly": False, "secure": True, "sameSite": "Lax"})
out = pathlib.Path(os.path.expanduser("~/notebokki-state.json"))
out.write_text(json.dumps({"cookies": cookies, "origins": []}))
print("cookies:", len(cookies))
EOF
rm ~/cookie-header.txt
```

This prints only a count, never values. A `Cookie` header has no domain information, so the script
marks every cookie as `.google.com`. That is the assumption to check first if setup is rejected.

Another route is a browser extension that exports Playwright storage state. Any file with the shape
above works.

---

## 4. Run setup

```bash
uv run notebokki setup --from-file ~/notebokki-state.json
rm ~/notebokki-state.json
```

You can also pipe the file in: `uv run notebokki setup < ~/notebokki-state.json`. Setup does **not**
accept the payload as a command-line argument, because arguments are visible in shell history and to
other processes.

What setup does:

1. Checks the cookie set, as described in step 3.
2. Writes the session to `~/.config/notebokki/session/storage_state.json`, then checks the file mode
   and refuses unless it is exactly `0600`.
3. Opens each registry entry with one request per topic and reports any it cannot reach, so a
   mistyped URL fails now, not in the middle of a task.

A good run ends with `All N registry entries are reachable.`

If a new session fails to authenticate, setup restores your previous one. If the first session ever
fails, setup removes it.

---

## 5. Connect it to Claude

### Claude Code

For every project on this machine:

```bash
claude mcp add --scope user notebokki -- uv run --directory /absolute/path/to/notebokki notebokki serve
```

For one project only, run the same command from that project with `--scope local` (the default).
Avoid `--scope project`: it writes a machine-specific path into a file meant to be committed.

Restart Claude Code, then run `/mcp`. `notebokki` should show as connected, exposing `list_topics`,
`search` and `ask`.

### Claude Desktop

Add this to `claude_desktop_config.json`, then restart the app:

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

Put no credential in this file. The session is found through the config directory, not through
the launcher.

---

## 6. Tell Claude when to use it

Claude only uses the tools if it is inclined to. Add one line to a project's `CLAUDE.md`, or to
`~/.claude/CLAUDE.md` to cover every project:

```markdown
@/absolute/path/to/notebokki/CLAUDE.BUSINESS-RULE.md
```

That file tells Claude to consult notebokki before it relies on a business rule it cannot derive
from the code, to prefer `search` for quick lookups, to run slow `ask` calls in a background
subagent, and to cite the document name from every result.

---

## 7. Check that it works

Start a Claude session and give it a real business-rule task **without naming a topic or a mode**,
for example "what does the lending form require?" Check three things:

- Claude chose the right topic.
- Claude chose a sensible tool: `search` for exact wording, `ask` for an explanation.
- The result names the source document.

A wrong pick means a registry description or a tool description needs rewording. It does not mean the
code is broken.

---

## Troubleshooting

| You see | Meaning | Fix |
|---|---|---|
| `Unknown topic 'x'. Valid topics: ...` | The topic name is not in the registry | Use a name from the list, or add it to the registry |
| `Session is missing, expired or invalid. Re-run notebokki setup` | The Google session ended | Capture a new session (step 3), run setup, then restart the MCP server |
| `Notebook is missing or no longer shared ... Registry file: ...` | That entry points at a deleted or unshared notebook | Fix or remove the entry in the registry file |
| `Request failed upstream (...)` | Throttling or a NotebookLM-side problem | Wait and retry |
| `The registry is unusable: ...` | Missing, empty, or invalid registry file | Fix the file, then restart the MCP server |
| `Could not make ... owner-only (mode 0600)` | The path is on a drive that ignores permissions, usually `/mnt/c` | Use a path on the Linux filesystem |
| `The payload is missing required cookies: ...` | The capture lacks a cookie | Capture again while signed in; check the cookie names listed |
| `The payload needs a secondary binding` | `OSID`, or `APISID`+`SAPISID`+`LSID`, is missing | Capture again from the Network tab, not `document.cookie` |
| Tools missing in Claude | The server loads at session start | Restart Claude Code or Desktop, then check `/mcp` |
| `ask` takes 30-40 seconds | NotebookLM generates the answer | Use `search` for lookups, or run `ask` in a background subagent |

After you fix a registry or session problem, **restart the MCP server**. It reads both once, at
start.

## Maintenance

- **Session expiry.** Sessions expire on Google's schedule, and notebokki has not measured how often.
  Re-run steps 3 and 4 when the tools tell you to.
- **Adding a notebook.** Add an entry to the registry and run `notebokki setup` to validate it.
- **Removing your session.** Delete `~/.config/notebokki/session/`. To make the session itself
  unusable, sign out of it in your Google account. There is no `logout` command.
- **Upgrading the library.** `notebooklm-py` is pinned. A bump should be deliberate: run
  `uv run pytest tests/test_library_surface.py` first. It fails loudly if the surface changed.
