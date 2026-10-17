"""The only module that imports the pinned NotebookLM library (KTD2).

Everything else talks to `Gateway`. The library is reached through exactly three members:
`sources.list`, `sources.search` and `chat.ask`. Nothing here adds, edits or removes notebook
content, sends a conversation identifier, or touches a chat thread's lifecycle (R8, R10).
"""

import json
import logging
import sys
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

import notebooklm

from . import errors

DEFAULT_PASSAGES = 5
MAX_PASSAGES = 20
# Explicit, not inherited: the library's defaults retry a throttled call with backoff behind a
# long chat timeout, turning throttling into minutes of latency instead of a classifiable error.
RATE_LIMIT_RETRIES = 1
SERVER_ERROR_RETRIES = 1
REQUEST_TIMEOUT = 30.0
CHAT_TIMEOUT = 60.0

_SESSION_TEXT = ("CSRF token not found", "Authentication expired")
_PINNED_LOGGERS = ("notebooklm", "httpx", "httpcore", "mcp")


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    title: str
    resolved: bool
    cited_text: str | None = None


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[SourceRef]


@dataclass(frozen=True)
class Passage:
    text: str
    rank: int
    source_id: str
    source_title: str
    resolved: bool


class _CookieValueFilter(logging.Filter):
    def __init__(self, values):
        super().__init__()
        self._values = [v for v in values if v]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a record that cannot render is dropped, never risked
            return False
        return not any(v in message for v in self._values)


def install_log_guard(secret_values) -> None:
    """Keep cookie values out of stderr, which a stdio host captures into persistent logs."""
    guard = _CookieValueFilter(secret_values)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stderr))
    for handler in root.handlers:
        handler.addFilter(guard)
    for name in _PINNED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _cookie_values(session_path: Path) -> list[str]:
    try:
        data = json.loads(Path(session_path).read_text(encoding="utf-8"))
        return [str(c.get("value", "")) for c in data.get("cookies", []) if isinstance(c, dict)]
    except Exception:  # noqa: BLE001 - unreadable session means no values to guard
        return []


def classify(exc: BaseException) -> errors.NotebokkiError:
    """Map a library failure to one of the four branches. Never carries the original text."""
    if isinstance(exc, errors.NotebokkiError):
        return exc
    if isinstance(exc, (notebooklm.AuthError, FileNotFoundError, PermissionError)):
        return errors.SessionError()
    if isinstance(exc, ValueError) and any(s in str(exc) for s in _SESSION_TEXT):
        return errors.SessionError()
    if isinstance(exc, notebooklm.NotebookNotFoundError):
        return errors.NotebookUnreachableError()
    return errors.UpstreamError(type(exc).__name__)


@contextmanager
def _classified():
    """Turn any library failure into one of the four branches. Catches Exception, not
    BaseException, so cancellation still propagates."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - every failure must land in a branch (KTD7)
        raise classify(exc) from None


@asynccontextmanager
async def _open_library_client(path: Path):
    ctx = notebooklm.NotebookLMClient.from_storage(
        str(path),
        timeout=REQUEST_TIMEOUT,
        rate_limit_max_retries=RATE_LIMIT_RETRIES,
        server_error_max_retries=SERVER_ERROR_RETRIES,
        chat_timeout=CHAT_TIMEOUT,
    )
    async with ctx as client:
        yield client


class Gateway:
    """One client, opened at server start and closed at shutdown (KTD13)."""

    def __init__(self, session_path: Path, *, client_factory=_open_library_client):
        self._path = Path(session_path)
        self._factory = client_factory
        self._stack = AsyncExitStack()
        self._client = None
        self._titles: dict[str, dict[str, str | None]] = {}

    async def __aenter__(self) -> "Gateway":  # noqa: PYI034
        install_log_guard(_cookie_values(self._path))
        with _classified():
            self._client = await self._stack.enter_async_context(self._factory(self._path))
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def prime(self, notebook_id: str) -> int:
        """One notebook-scoped listing that primes the title map. Returns the source count."""
        return len(await self._fetch_titles(notebook_id))

    async def ask(self, notebook_id: str, question: str) -> Answer:
        with _classified():
            result = await self._client.chat.ask(notebook_id, question)
        refs: dict[str, str | None] = {}
        for r in result.references or []:
            refs.setdefault(r.source_id, r.cited_text)
        titles = await self._resolve(notebook_id, list(refs))
        return Answer(
            answer=result.answer,
            sources=[SourceRef(sid, *titles[sid], cited_text=refs[sid]) for sid in refs],
        )

    async def search(
        self, notebook_id: str, query: str, limit: int = DEFAULT_PASSAGES
    ) -> list[Passage]:
        with _classified():
            chunks = await self._client.sources.search(notebook_id, query, limit=limit)
        titles = await self._resolve(notebook_id, [c.source_id for c in chunks])
        return [Passage(c.text, c.rank, c.source_id, *titles[c.source_id]) for c in chunks]

    async def _fetch_titles(self, notebook_id: str) -> dict[str, str | None]:
        with _classified():
            sources = await self._client.sources.list(notebook_id)
        self._titles[notebook_id] = {s.id: s.title for s in sources}
        return self._titles[notebook_id]

    async def _resolve(self, notebook_id: str, ids: list[str]) -> dict[str, tuple[str, bool]]:
        if not ids:
            return {}
        known = self._titles.get(notebook_id)
        if known is None:
            known = await self._fetch_titles(notebook_id)
        elif any(i not in known for i in ids):
            known = await self._fetch_titles(notebook_id)  # refresh a stale map once on a miss
        out = {}
        for i in ids:
            title = known.get(i)
            out[i] = (title, True) if title else (f"[unresolved source {i}]", False)
        return out
