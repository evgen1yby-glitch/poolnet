"""`load_sources` tests: the flat-YAML traps that break naive readers.

The bug that motivates this file: the reader kept a single `current` dict and
ignored indentation entirely, so the file-level knobs that sit *after* the
`sources:` list (`canary_token`, `source_pass_rate`, ...) were folded into the
last `- url:` entry and splatted into `Source(**current)`, which raises
`TypeError: Source.__init__() got an unexpected keyword argument
'source_pass_rate'`. Separately, even when that did not raise, the knobs were
never returned to the caller at all, so the pipeline and the API silently read
defaults instead of the configured values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.fetcher import load_sources  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"


def test_real_config_loads_without_raising():
    """The shipped `config/sources.yaml` must parse. This is the regression."""
    sources, _settings = load_sources(CONFIG)
    assert sources, "the real config lists six sources; an empty list is a silent failure"
    assert all(s.url.startswith(("https://", "http://")) for s in sources)
    # 33 sources: 26 built up across three passes on 2026-10-16, plus seven
    # verified in the 2026-10-23 audit. Pinned because a source silently
    # dropped from the file is invisible otherwise — the pool just gets smaller.
    assert len(sources) == 33
    assert {s.kind for s in sources if s.kind} == {"proxyfreeonly", "vpngate", "ipspeed"}


def test_file_level_knobs_are_returned_not_swallowed():
    """Operational settings are loaded rather than silently swallowed."""
    _sources, settings = load_sources(CONFIG)
    assert settings["source_pass_rate"] == 1.0
    assert settings["protocol_reliability"] == 0.5
    assert settings["canary_token"] == ""
    # Empty, and that is the assertion — the same reasoning as `bot_username`
    # below. A checked-in origin is one operator's address: it names a server
    # every other install does not run, so the URL-bearing subscription headers
    # would advertise someone else's host. The deployment supplies it through
    # `HUB_BASE_URL` (read by both the API and the bot), and an empty value
    # means those headers are dropped rather than rendered blank.
    assert settings["base_url"] == "", (
        "the shipped config must not carry an origin; set HUB_BASE_URL per deploy"
    )
    # Ships empty, and that is the assertion. `bot_username` gates the landing
    # page's country links: the key must survive the loader, and it must not
    # arrive as a placeholder, because a placeholder builds `t.me/<someone
    # else's bot>` links on an install whose own bot is unnamed. A value that
    # is silently dropped would look identical to this in the UI — plain cards
    # either way — so the difference is only visible here.
    assert settings["bot_username"] == "", (
        "a shipped bot_username would link every install to one bot; it must be set per-deploy"
    )
    # The list itself must not leak into the settings mapping.
    assert "sources" not in settings
    assert "url" not in settings


def test_a_bot_username_in_a_file_reaches_the_api(tmp_path):
    """The whole wiring, in the order the operator experiences it.

    `create_app` reads `bot_username` out of a settings *dict*. That dict is
    produced here, by the file loader, from a file — so a key that `FILE_SETTINGS`
    forgets, or that the loader drops, fails here instead of producing a
    deployment whose cards point nowhere. The endpoint that consumes it is
    `tests/test_country_links.py`'s job; this is the half that fills it.
    """
    from hub.api import create_app
    from fastapi.testclient import TestClient

    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        'sources:\n'
        '  - url: https://www.vpngate.net/api/iphone/\n'
        '    name: vpngate/api\n'
        '    kind: vpngate\n'
        'base_url: "https://hub.example"\n'
        'bot_username: "@my_hub_bot"\n',
        encoding="utf-8",
    )
    _sources, settings = load_sources(cfg)
    assert settings["bot_username"] == "@my_hub_bot", settings

    api = TestClient(create_app(store=None, sources=settings))
    assert api.get("/api/v1/bot").json() == {"username": "my_hub_bot"}


def test_source_fields_are_not_polluted_by_knobs():
    """No Source may carry a knob as a field.

    The old reader attached every top-level key to the *last* source, so this
    node is also the regression guard for the crash itself.
    """
    sources, _settings = load_sources(CONFIG)
    for source in sources:
        assert set(vars(source)) == {"url", "name", "enabled", "include", "exclude", "kind"}


def test_indented_keys_stay_with_their_source(tmp_path):
    """Indentation is what separates a source field from a file-level knob.

    A key indented under `- url:` belongs to that source; a key at column 0
    belongs to the file. The reader must honour that boundary rather than
    deriving it from "is the value non-empty", which is not the same question.
    """
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "sources:\n"
        '  - url: https://example.test/a\n'
        '    name: A\n'
        "    enabled: false\n"
        "    include: vless, trojan\n"
        "  - url: https://example.test/b\n"
        "    name: B\n"
        "    exclude: vmess\n"
        "\n"
        "source_pass_rate: 0.75\n"
        "protocol_reliability: 0.4\n",
        encoding="utf-8",
    )
    sources, settings = load_sources(cfg)
    assert [s.name for s in sources] == ["A", "B"]
    assert sources[0].enabled is False
    assert sources[0].include == ("vless", "trojan")
    assert sources[1].exclude == ("vmess",)
    assert settings["source_pass_rate"] == 0.75
    assert settings["protocol_reliability"] == 0.4


def test_json_root_is_still_accepted(tmp_path):
    """A JSON array is the documented alternative shape and must keep working."""
    cfg = tmp_path / "sources.json"
    cfg.write_text('[{"url": "https://example.test/a", "name": "A"}]', encoding="utf-8")
    sources, settings = load_sources(cfg)
    assert [s.name for s in sources] == ["A"]
    assert settings == {}


def test_json_object_root_is_accepted_with_settings(tmp_path):
    """A JSON object carrying both `sources` and knobs."""
    cfg = tmp_path / "sources.json"
    cfg.write_text(
        '{"sources": [{"url": "https://example.test/a"}], "base_url": "https://sub.test"}',
        encoding="utf-8",
    )
    sources, settings = load_sources(cfg)
    assert [s.url for s in sources] == ["https://example.test/a"]
    assert settings["base_url"] == "https://sub.test"


def test_empty_document_is_not_an_error(tmp_path):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text("", encoding="utf-8")
    assert load_sources(cfg) == ([], {})


def test_unknown_top_level_key_is_reported_not_fatal(tmp_path):
    """A typo'd knob must be visible, not silently ignored or fatal.

    Silently dropping it means a reviewer cannot tell "not set" from "misspelt",
    which is exactly the class of bug that hid the knobs for so long.
    """
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "sources:\n  - url: https://example.test/a\nbase_url_typo: https://sub.test\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="base_url_typo"):
        load_sources(cfg)
