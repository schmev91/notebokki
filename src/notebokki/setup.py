"""One-step setup: ingest a session safely, prove its file mode, prove every registry entry
is reachable (R14, R15, R18; KTD4, KTD5, KTD9).

The payload arrives out of band only (piped stdin or --from-file). It is never read from argv,
which is visible in shell history and to any process, nor from an interactive prompt, whose
canonical-mode line limit would silently truncate a multi-kilobyte cookie set.
"""

import asyncio
import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from . import config, errors
from .notebooklm import Gateway
from .registry import Registry, RegistryError

HARD_REQUIRED = ("SID", "__Secure-1PSIDTS")
SECONDARY_ALL = ("APISID", "SAPISID", "LSID")
SECONDARY_ANY = "OSID"


class SetupError(Exception):
    """A setup input problem. Messages name cookies, never their values."""


def validate_payload(text: str | None) -> dict:
    if not text or not text.strip():
        raise SetupError("No session payload supplied. Pipe it on stdin or use --from-file.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise SetupError("The session payload is not valid JSON.") from None
    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list):
        raise SetupError(
            "The payload must be a Playwright storage-state object with a 'cookies' array "
            "(not a DevTools cookie dump)."
        )
    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    missing = [n for n in HARD_REQUIRED if n not in names]
    if missing:
        raise SetupError(f"The payload is missing required cookies: {', '.join(missing)}.")
    if SECONDARY_ANY not in names and not all(n in names for n in SECONDARY_ALL):
        raise SetupError(
            f"The payload needs a secondary binding: {SECONDARY_ANY}, or all of "
            f"{', '.join(SECONDARY_ALL)}. The library would only warn here; setup refuses so a "
            "bad capture cannot stay latent until the first query."
        )
    return data


def _file_mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def write_session(path: Path, text: str) -> None:
    """Write owner-only to a sibling temp file, stat it and require exactly 0600, then replace
    the target atomically. chmod's exit status is not evidence: on a /mnt DrvFs mount it
    succeeds while leaving the mode at 777 (KTD9). A failure leaves any prior session intact."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:  # buffered write: a short os.write must not truncate it
        os.fchmod(f.fileno(), 0o600)
        f.write(text.encode("utf-8"))
    if _file_mode(tmp) != 0o600:
        tmp.unlink(missing_ok=True)
        raise SetupError(
            f"Could not make {path} owner-only (mode 0600); the filesystem ignores permissions. "
            "This is typical of a /mnt/c (DrvFs) path. Use a path on the Linux filesystem."
        )
    os.replace(tmp, path)


def _rollback(path: Path, previous: bytes | None) -> str:
    """A session that did not authenticate must not replace a working one."""
    if previous is None:
        path.unlink(missing_ok=True)
        return "The new session was removed."
    write_session(path, previous.decode("utf-8"))
    return "The previous session was restored."


async def run_setup(
    *,
    payload_text: str | None,
    registry_path: Path,
    session_path: Path,
    gateway_factory: Callable[[Path], object] = Gateway,
    out: Callable[[str], None] = print,
    argv_payload: str | None = None,
) -> int:
    if argv_payload is not None:
        out(
            "Refusing a session payload given as a command-line argument: argv is visible in "
            "shell history and to other processes. Pipe it on stdin or use --from-file."
        )
        return 2
    try:
        previous = session_path.read_bytes() if session_path.exists() else None
        write_session(session_path, json.dumps(validate_payload(payload_text)))
    except (SetupError, OSError) as exc:
        out(f"Setup failed: {exc}")
        return 2
    out(f"Session saved to {session_path} (mode 0600).")
    out("This file grants full Google account access while valid. Keep it out of any repository.")

    try:
        entries = Registry.load(registry_path).entries()
    except RegistryError as exc:
        out(f"Session saved, but the registry could not be validated: {exc}")
        return 2

    failed, transient = [], []
    try:
        async with gateway_factory(session_path) as gateway:
            for entry in entries:
                try:
                    count = await gateway.prime(entry.notebook_id)
                except errors.NotebookUnreachableError:
                    failed.append(entry.topic)
                    out(
                        f"  FAIL  {entry.topic}: notebook is unreachable (missing or not "
                        f"shared). Fix its entry in {registry_path}."
                    )
                except errors.UpstreamError as exc:
                    transient.append(entry.topic)
                    out(
                        f"  WAIT  {entry.topic}: transient NotebookLM condition "
                        f"({exc.type_name}); the entry itself may be fine. Re-run setup later."
                    )
                else:
                    out(f"  ok    {entry.topic}: reachable, {count} sources")
    except errors.SessionError as exc:
        out(f"Setup stopped: {exc} {_rollback(session_path, previous)}")
        return 1
    except errors.NotebokkiError as exc:
        out(f"Setup stopped before validation: {exc} The session was saved; re-run setup later.")
        return 1
    if failed or transient:
        out(f"{len(failed)} failing entries, {len(transient)} not checked due to transient errors.")
        return 1
    out(f"All {len(entries)} registry entries are reachable.")
    return 0


def read_payload(from_file: str | None, stdin=None) -> str | None:
    if from_file:
        try:
            return Path(from_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise SetupError(f"Could not read the session file {from_file}.") from None
    stdin = stdin or sys.stdin
    return None if stdin.isatty() else stdin.read()


def main(from_file: str | None, extra: list[str]) -> int:
    try:
        payload = None if extra else read_payload(from_file)
    except SetupError as exc:
        print(f"Setup failed: {exc}")
        return 2
    return asyncio.run(
        run_setup(
            payload_text=payload,
            registry_path=config.registry_path(),
            session_path=config.session_path(),
            argv_payload=" ".join(extra) if extra else None,
        )
    )
