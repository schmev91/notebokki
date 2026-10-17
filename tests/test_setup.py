import json

import pytest

from notebokki import errors, setup

SECRET = "S3cr3tCookieValue-abcdef123456"
NB1 = "https://notebooklm.google.com/notebook/aaa111"
NB2 = "https://notebooklm.google.com/notebook/bbb222"


def payload(*names, extra=None):
    cookies = [
        {"name": n, "value": f"{SECRET}-{n}", "domain": ".google.com", "path": "/"} for n in names
    ]
    return json.dumps({"cookies": cookies + (extra or []), "origins": []})


GOOD = payload("SID", "__Secure-1PSIDTS", "OSID")
GOOD_ALT = payload("SID", "__Secure-1PSIDTS", "APISID", "SAPISID", "LSID")


class FakeGateway:
    def __init__(self, outcomes):
        self.outcomes = outcomes  # notebook_id -> int | Exception
        self.primed = []
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *a):
        return None

    async def prime(self, notebook_id):
        self.primed.append(notebook_id)
        out = self.outcomes[notebook_id]
        if isinstance(out, Exception):
            raise out
        return out


def registry(tmp_path, *urls):
    p = tmp_path / "registry.json"
    p.write_text(
        json.dumps({f"t{i}": {"url": u, "description": f"d{i}"} for i, u in enumerate(urls)})
    )
    return p


async def run(tmp_path, text, gw, *urls, **kw):
    out = []
    session = tmp_path / "cfg" / "session" / "storage_state.json"
    code = await setup.run_setup(
        payload_text=text,
        registry_path=registry(tmp_path, *urls),
        session_path=session,
        gateway_factory=lambda path: gw,
        out=out.append,
        **kw,
    )
    return code, "\n".join(out), session


def test_missing_hard_required_cookie_rejected_by_name():
    with pytest.raises(setup.SetupError) as ei:
        setup.validate_payload(payload("SID", "OSID"))
    assert "__Secure-1PSIDTS" in str(ei.value)
    assert SECRET not in str(ei.value)


def test_missing_secondary_binding_rejected_though_library_would_only_warn():
    with pytest.raises(setup.SetupError, match="OSID"):
        setup.validate_payload(payload("SID", "__Secure-1PSIDTS"))


def test_either_secondary_binding_form_is_accepted():
    setup.validate_payload(GOOD)
    setup.validate_payload(GOOD_ALT)
    with pytest.raises(setup.SetupError):
        setup.validate_payload(payload("SID", "__Secure-1PSIDTS", "APISID", "SAPISID"))


@pytest.mark.parametrize("bad", ["", "not json", "[]", '{"cookies": "x"}', '{"origins": []}'])
def test_malformed_payloads_rejected(bad):
    with pytest.raises(setup.SetupError):
        setup.validate_payload(bad)


async def test_argv_payload_is_rejected_with_stdin_guidance(tmp_path):
    gw = FakeGateway({})
    code, out, session = await run(tmp_path, None, gw, NB1, argv_payload=GOOD)
    assert code != 0
    assert "stdin" in out
    assert SECRET not in out
    assert not session.exists() and not gw.entered


async def test_all_reachable_reports_success_one_call_per_topic(tmp_path):
    gw = FakeGateway({"aaa111": 3, "bbb222": 5})
    code, _out, session = await run(tmp_path, GOOD, gw, NB1, NB2)
    assert code == 0
    assert gw.primed == ["aaa111", "bbb222"]
    assert oct(session.stat().st_mode & 0o777) == "0o600"
    assert oct(session.parent.stat().st_mode & 0o777) == "0o700"


async def test_unreachable_entry_reported_and_no_overall_success(tmp_path):
    gw = FakeGateway({"aaa111": 3, "bbb222": errors.NotebookUnreachableError()})
    code, out, _ = await run(tmp_path, GOOD, gw, NB1, NB2)
    assert code != 0
    assert "t1" in out and "unreachable" in out.lower()
    assert "t0" in out


async def test_throttle_is_transient_not_a_failing_entry(tmp_path):
    gw = FakeGateway({"aaa111": errors.UpstreamError("RateLimitError")})
    code, out, _ = await run(tmp_path, GOOD, gw, NB1)
    assert code != 0
    assert "transient" in out.lower()
    assert "unreachable" not in out.lower()
    assert "re-run" in out.lower()


async def test_dead_session_during_validation_points_at_setup_not_registry(tmp_path):
    gw = FakeGateway({"aaa111": errors.SessionError()})
    code, out, _ = await run(tmp_path, GOOD, gw, NB1)
    assert code != 0
    assert "session" in out.lower()
    assert "unreachable" not in out.lower()


async def test_output_names_path_and_scope_and_has_no_cookie_value(tmp_path):
    gw = FakeGateway({"aaa111": 1})
    _code, out, session = await run(tmp_path, GOOD, gw, NB1)
    assert str(session) in out
    assert "full" in out.lower() and "account" in out.lower()
    assert SECRET not in out


async def test_wrong_mode_fails_and_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_file_mode", lambda path: 0o777)
    gw = FakeGateway({"aaa111": 1})
    code, out, session = await run(tmp_path, GOOD, gw, NB1)
    assert code != 0
    assert not session.exists()
    assert "0600" in out and "/mnt" in out
    assert not gw.entered


async def test_bad_registry_stops_before_any_call_but_keeps_session(tmp_path):
    gw = FakeGateway({})
    out = []
    session = tmp_path / "cfg" / "session" / "storage_state.json"
    (tmp_path / "registry.json").write_text("{nope")
    code = await setup.run_setup(
        payload_text=GOOD,
        registry_path=tmp_path / "registry.json",
        session_path=session,
        gateway_factory=lambda p: gw,
        out=out.append,
    )
    assert code != 0 and gw.primed == []


def test_cli_rejects_payload_given_as_argument(capsys, tmp_path, monkeypatch):
    from notebokki.__main__ import main

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["setup", GOOD]) == 2
    assert "stdin" in capsys.readouterr().out
    assert not (tmp_path / "notebokki").exists()
