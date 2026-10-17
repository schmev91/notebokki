"""Pins the slice of notebooklm-py that notebokki relies on.

The faked-boundary tests stay green through a changed return shape, which would silently strip
the attribution R11/R12 exist to guarantee. These assertions introspect the installed package,
so a bad upgrade fails here, loudly, with no network and no credentials.
"""

import dataclasses
import inspect
from importlib import metadata

import notebooklm
from notebooklm import _chat, _sources
from notebooklm._auth import extraction

PINNED = "0.8.4"


def params(fn):
    return list(inspect.signature(fn).parameters)


def fields(cls):
    return {f.name for f in dataclasses.fields(cls)}


def test_installed_version_is_the_pinned_release():
    assert metadata.version("notebooklm-py") == PINNED


def test_sources_search_signature():
    fn = _sources.SourcesAPI.search
    assert inspect.iscoroutinefunction(fn)
    p = inspect.signature(fn).parameters
    assert params(fn)[1:3] == ["notebook_id", "query"]
    assert p["source_ids"].kind is inspect.Parameter.KEYWORD_ONLY
    assert p["limit"].kind is inspect.Parameter.KEYWORD_ONLY


def test_relevant_chunk_fields():
    assert {"source_id", "text", "rank"} <= fields(notebooklm.RelevantChunk)


def test_sources_list_signature_and_source_fields():
    fn = _sources.SourcesAPI.list
    assert inspect.iscoroutinefunction(fn)
    assert params(fn)[1] == "notebook_id"
    assert {"id", "title"} <= fields(notebooklm.Source)


def test_chat_ask_signature_and_result_fields():
    fn = _chat.ChatAPI.ask
    assert inspect.iscoroutinefunction(fn)
    assert params(fn)[1:3] == ["notebook_id", "question"]
    assert "conversation_id" in params(fn)  # we must be able to leave it unset
    assert {"answer", "references"} <= fields(notebooklm.AskResult)
    assert {"source_id", "cited_text"} <= fields(notebooklm.ChatReference)


def test_nullable_fields_stay_nullable():
    hints = {f.name: str(f.type) for f in dataclasses.fields(notebooklm.Source)}
    assert "None" in hints["title"]
    hints = {f.name: str(f.type) for f in dataclasses.fields(notebooklm.ChatReference)}
    assert "None" in hints["cited_text"]


def test_from_storage_takes_explicit_path_and_tunables():
    p = inspect.signature(notebooklm.NotebookLMClient.from_storage).parameters
    for name in ("path", "rate_limit_max_retries", "server_error_max_retries", "chat_timeout"):
        assert name in p


def test_client_is_an_async_context_manager():
    c = notebooklm.NotebookLMClient
    assert inspect.iscoroutinefunction(c.__aenter__)
    assert inspect.iscoroutinefunction(c.__aexit__)


def test_failure_types_used_for_classification():
    assert issubclass(notebooklm.AuthError, notebooklm.NotebookLMError)
    assert issubclass(notebooklm.RateLimitError, notebooklm.NotebookLMError)
    assert issubclass(notebooklm.NotebookNotFoundError, notebooklm.NotebookLMError)
    assert issubclass(notebooklm.ServerError, notebooklm.NotebookLMError)


def test_legacy_session_open_failure_text_is_still_present():
    # KTD7: session-open failures arrive as a bare ValueError whose text carries these
    # substrings; the classifier matches on them, so they must still exist upstream.
    src = inspect.getsource(extraction)
    assert "Authentication expired" in src
    assert "CSRF token" in src
