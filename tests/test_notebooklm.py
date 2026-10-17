import ast
import json
import logging
import pathlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import notebooklm
import pytest

from notebokki import errors
from notebokki.notebooklm import Gateway, install_log_guard

NB = "nb-1"
SECRET = "S3cr3tCookieValue-abcdef123456"


class Recorder:
    """Fake library client that fails on any attribute outside the three allowlisted members."""

    def __init__(self, titles=None, chunks=(), answer=None, raises=None):
        self.accessed = []
        self.calls = []
        self._titles = titles if titles is not None else {}
        self._chunks = list(chunks)
        self._answer = answer
        self._raises = raises
        self.sources = _Guard(self, "sources", {"list": self._list, "search": self._search})
        self.chat = _Guard(self, "chat", {"ask": self._ask})

    def __getattr__(self, name):
        raise AssertionError(f"non-allowlisted client attribute: {name}")

    async def _list(self, notebook_id, **kw):
        self.calls.append(("sources.list", (notebook_id,), kw))
        if self._raises:
            raise self._raises
        return [SimpleNamespace(id=i, title=t) for i, t in self._titles.items()]

    async def _search(self, notebook_id, query, **kw):
        self.calls.append(("sources.search", (notebook_id, query), kw))
        if self._raises:
            raise self._raises
        return self._chunks

    async def _ask(self, notebook_id, question, **kw):
        self.calls.append(("chat.ask", (notebook_id, question), kw))
        if self._raises:
            raise self._raises
        return self._answer


class _Guard:
    def __init__(self, owner, prefix, members):
        object.__setattr__(self, "_m", members)
        object.__setattr__(self, "_o", owner)
        object.__setattr__(self, "_p", prefix)

    def __getattr__(self, name):
        if name not in self._m:
            raise AssertionError(f"non-allowlisted library member: {self._p}.{name}")
        self._o.accessed.append(f"{self._p}.{name}")
        return self._m[name]


def session_file(tmp_path):
    p = tmp_path / "session" / "storage_state.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"cookies": [{"name": "SID", "value": SECRET}], "origins": []}))
    return p


def factory_for(client, seen=None, open_error=None):
    @asynccontextmanager
    async def factory(path):
        if seen is not None:
            seen.append(path)
        if open_error:
            raise open_error
        yield client

    return factory


async def open_gateway(tmp_path, client, **kw):
    gw = Gateway(session_file(tmp_path), client_factory=factory_for(client, **kw))
    await gw.__aenter__()
    return gw


def ref(source_id, cited="quoted"):
    return SimpleNamespace(source_id=source_id, cited_text=cited)


def chunk(source_id, text, rank):
    return SimpleNamespace(source_id=source_id, text=text, rank=rank)


async def test_ask_returns_answer_and_resolved_titles(tmp_path):
    client = Recorder(
        titles={"s1": "Billing Spec", "s2": "Refund Policy"},
        answer=SimpleNamespace(answer="42", references=[ref("s1"), ref("s2"), ref("s1")]),
    )
    gw = await open_gateway(tmp_path, client)
    res = await gw.ask(NB, "q?")
    assert res.answer == "42"
    assert [s.title for s in res.sources] == ["Billing Spec", "Refund Policy"]


async def test_search_preserves_rank_order_and_text_verbatim(tmp_path):
    text = "  Exact wording\twith   odd   spacing\n"
    client = Recorder(
        titles={"s1": "Doc A"},
        chunks=[chunk("s1", text, 1), chunk("s1", "second", 2)],
    )
    gw = await open_gateway(tmp_path, client)
    out = await gw.search(NB, "q")
    assert [p.text for p in out] == [text, "second"]
    assert [p.rank for p in out] == [1, 2]
    assert all(p.source_title == "Doc A" for p in out)


async def test_unanswerable_question_passes_library_outcome_through(tmp_path):
    client = Recorder(answer=SimpleNamespace(answer="", references=[]))
    gw = await open_gateway(tmp_path, client)
    res = await gw.ask(NB, "q")
    assert res.answer == ""
    assert res.sources == []


async def test_ask_sends_only_the_question_and_never_deletes(tmp_path):
    client = Recorder(answer=SimpleNamespace(answer="a", references=[]))
    gw = await open_gateway(tmp_path, client)
    await gw.ask(NB, "first")
    await gw.ask(NB, "second")
    asks = [c for c in client.calls if c[0] == "chat.ask"]
    assert [c[1] for c in asks] == [(NB, "first"), (NB, "second")]
    assert all(c[2] == {} for c in asks)  # no conversation_id, no source_ids
    assert not any("delete" in c[0] for c in client.calls)


async def test_client_built_from_explicit_storage_path(tmp_path):
    seen = []
    p = session_file(tmp_path)
    gw = Gateway(p, client_factory=factory_for(Recorder(), seen=seen))
    await gw.__aenter__()
    assert seen == [p]


def test_no_environment_credential_login_or_browser_in_module():
    src = pathlib.Path(__import__("notebokki.notebooklm", fromlist=["x"]).__file__).read_text()
    for needle in (
        "environ",
        "getenv",
        "NOTEBOOKLM_AUTH_JSON",
        "playwright",
        "subprocess",
        "login",
    ):
        assert needle not in src, needle


@pytest.mark.parametrize(
    "exc,expected",
    [
        (notebooklm.AuthError("x"), errors.SessionError),
        (ValueError("CSRF token not found. Authentication expired"), errors.SessionError),
        (ValueError("Authentication expired or invalid"), errors.SessionError),
        (notebooklm.NotebookNotFoundError("x"), errors.NotebookUnreachableError),
        (notebooklm.RateLimitError("x"), errors.UpstreamError),
        (RuntimeError("boom"), errors.UpstreamError),
    ],
)
async def test_four_branch_classification(tmp_path, exc, expected):
    gw = await open_gateway(tmp_path, Recorder(raises=exc))
    with pytest.raises(expected):
        await gw.search(NB, "q")


async def test_open_time_failures_classify_as_session(tmp_path):
    for err in (ValueError("CSRF token not found"), notebooklm.AuthError("x"), FileNotFoundError()):
        gw = Gateway(tmp_path / "nope.json", client_factory=factory_for(Recorder(), open_error=err))
        with pytest.raises(errors.SessionError):
            await gw.__aenter__()


async def test_unrecognized_exception_is_upstream_with_type_name_only(tmp_path):
    gw = await open_gateway(tmp_path, Recorder(raises=KeyError(SECRET)))
    with pytest.raises(errors.UpstreamError) as ei:
        await gw.search(NB, "q")
    assert ei.value.type_name == "KeyError"
    assert SECRET not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


async def test_no_classified_error_carries_a_cookie_value(tmp_path):
    for exc in (
        notebooklm.AuthError(SECRET),
        ValueError(f"CSRF token not found {SECRET}"),
        notebooklm.NotebookNotFoundError(SECRET),
        RuntimeError(SECRET),
    ):
        gw = await open_gateway(tmp_path, Recorder(raises=exc))
        with pytest.raises(errors.NotebokkiError) as ei:
            await gw.ask(NB, "q")
        assert SECRET not in str(ei.value) and SECRET not in repr(ei.value)


async def test_title_map_fetched_once_across_queries(tmp_path):
    client = Recorder(
        titles={"s1": "Doc"},
        answer=SimpleNamespace(answer="a", references=[ref("s1")]),
        chunks=[chunk("s1", "t", 1)],
    )
    gw = await open_gateway(tmp_path, client)
    await gw.ask(NB, "q1")
    await gw.search(NB, "q2")
    assert [c[0] for c in client.calls].count("sources.list") == 1


async def test_missing_null_and_empty_titles_degrade_to_labelled_identifier(tmp_path):
    client = Recorder(
        titles={"s1": None, "s2": ""},
        answer=SimpleNamespace(
            answer="a", references=[ref("s1", cited=None), ref("s2"), ref("ghost")]
        ),
    )
    gw = await open_gateway(tmp_path, client)
    res = await gw.ask(NB, "q")
    assert [s.resolved for s in res.sources] == [False, False, False]
    assert all(s.source_id in s.title for s in res.sources)
    assert res.sources[0].cited_text is None


async def test_title_miss_refreshes_once_then_degrades(tmp_path):
    client = Recorder(
        titles={"s1": "Doc"}, chunks=[chunk("ghost", "t", 1), chunk("ghost2", "t", 2)]
    )
    gw = await open_gateway(tmp_path, client)
    await gw.prime(NB)
    await gw.search(NB, "q")
    assert [c[0] for c in client.calls].count("sources.list") == 2  # prime + one refresh


async def test_cold_miss_does_not_list_twice_and_empty_results_do_not_list(tmp_path):
    client = Recorder(titles={"s1": "Doc"}, chunks=[chunk("ghost", "t", 1)])
    gw = await open_gateway(tmp_path, client)
    await gw.search(NB, "q")
    assert [c[0] for c in client.calls].count("sources.list") == 1
    empty = Recorder(chunks=[])
    gw2 = await open_gateway(tmp_path, empty)
    await gw2.search(NB, "q")
    assert [c[0] for c in empty.calls].count("sources.list") == 0


async def test_prime_makes_exactly_one_list_call(tmp_path):
    client = Recorder(titles={"s1": "Doc", "s2": "Doc2"})
    gw = await open_gateway(tmp_path, client)
    assert await gw.prime(NB) == 2
    assert [c[0] for c in client.calls] == ["sources.list"]


async def test_only_allowlisted_members_touched(tmp_path):
    client = Recorder(
        titles={"s1": "D"},
        answer=SimpleNamespace(answer="a", references=[ref("s1")]),
        chunks=[chunk("s1", "t", 1)],
    )
    gw = await open_gateway(tmp_path, client)
    await gw.ask(NB, "q")
    await gw.search(NB, "q")
    await gw.prime(NB)
    assert set(client.accessed) <= {"sources.list", "sources.search", "chat.ask"}


def test_log_guard_suppresses_cookie_values_and_pins_levels():
    guard_records = []

    class Capture(logging.Handler):
        def emit(self, record):
            guard_records.append(record.getMessage())

    root = logging.getLogger()
    h = Capture()
    root.addHandler(h)
    try:
        install_log_guard([SECRET])
        for name in ("notebooklm", "httpx", "httpcore", "mcp"):
            assert logging.getLogger(name).level >= logging.WARNING
        logging.getLogger("notebooklm").warning("leak %s", SECRET)
        logging.getLogger("notebooklm").warning("benign message")
        assert guard_records == ["benign message"]
    finally:
        root.removeHandler(h)


def test_library_imported_by_exactly_one_module():
    src_dir = pathlib.Path(__import__("notebokki").__file__).parent
    importers = []
    for f in src_dir.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] == "notebooklm" for a in node.names
            ):
                importers.append(f.name)
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module or "").split(".")[0] == "notebooklm"
            ):
                importers.append(f.name)
    assert set(importers) == {"notebooklm.py"}


async def test_cancellation_is_not_swallowed_into_an_error_branch(tmp_path):
    import asyncio

    gw = await open_gateway(tmp_path, Recorder(raises=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await gw.search(NB, "q")


async def test_ask_survives_a_failed_title_lookup(tmp_path):
    class Flaky(Recorder):
        async def _list(self, notebook_id, **kw):
            raise RuntimeError("list down")

    client = Flaky(answer=SimpleNamespace(answer="the answer", references=[ref("s1")]))
    gw = await open_gateway(tmp_path, client)
    res = await gw.ask(NB, "q")
    assert res.answer == "the answer"
    assert res.sources[0].resolved is False
