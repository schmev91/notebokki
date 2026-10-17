import json

import pytest

from notebokki.registry import Registry, RegistryError

NB = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def write(path, obj):
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return path


def entry(url, desc="Billing rules"):
    return {"url": url, "description": desc}


def test_full_browser_url_resolves_to_bare_id(tmp_path):
    p = write(
        tmp_path / "r.json", {"billing": entry(f"https://notebooklm.google.com/notebook/{NB}")}
    )
    assert Registry.load(p).resolve("billing").notebook_id == NB


def test_url_with_query_and_alt_host_resolves(tmp_path):
    p = write(
        tmp_path / "r.json",
        {"a": entry(f"https://notebook.google.com/notebook/{NB}?authuser=1&pli=1")},
    )
    assert Registry.load(p).resolve("a").notebook_id == NB


def test_underivable_url_fails_naming_topic(tmp_path):
    p = write(tmp_path / "r.json", {"broken": entry("https://example.com/nothing")})
    with pytest.raises(RegistryError, match="broken"):
        Registry.load(p)


def test_unknown_topic_returns_none_with_no_near_match(tmp_path):
    p = write(
        tmp_path / "r.json", {"billing": entry(f"https://notebooklm.google.com/notebook/{NB}")}
    )
    reg = Registry.load(p)
    assert reg.resolve("bill") is None
    assert reg.resolve("Billing") is None
    assert reg.resolve("billing ") is None


def test_descriptions_available_for_listing(tmp_path):
    p = write(
        tmp_path / "r.json",
        {
            "billing": entry(f"https://notebooklm.google.com/notebook/{NB}", "Billing rules"),
            "ship": entry(f"https://notebooklm.google.com/notebook/{NB}x", "Shipping"),
        },
    )
    reg = Registry.load(p)
    assert reg.topics() == ["billing", "ship"]
    assert reg.resolve("billing").description == "Billing rules"
    assert [(e.topic, e.description) for e in reg.entries()] == [
        ("billing", "Billing rules"),
        ("ship", "Shipping"),
    ]


def test_absent_empty_and_invalid_are_distinct_errors(tmp_path):
    with pytest.raises(RegistryError, match="not found"):
        Registry.load(tmp_path / "missing.json")
    with pytest.raises(RegistryError, match="no topics"):
        Registry.load(write(tmp_path / "e.json", {}))
    with pytest.raises(RegistryError, match="not valid JSON"):
        Registry.load(write(tmp_path / "bad.json", "{nope"))


def test_entry_missing_description_fails_naming_topic(tmp_path):
    p = write(tmp_path / "r.json", {"x": {"url": f"https://notebooklm.google.com/notebook/{NB}"}})
    with pytest.raises(RegistryError, match="x"):
        Registry.load(p)
