"""The site view renderer: live numbers with the page's own copy as fallback.

These tests pin the contract the hub relies on at request time — no template
engine, no new dependencies, no exception when a field is absent. The static
pages are also rendered here, because a token left in production markup is a
visible `{{…}}` on the public site.
"""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hub.siteview import SiteRenderer  # noqa: E402

SITE_DIR = Path(__file__).resolve().parents[2] / "web" / "site"


def payload() -> dict:
    return {
        "vpn": {
            "generation": "gen-test",
            "verified": 150,
            "known": 997,
            "countries": 29,
            "protocols": [{"name": "vless", "n": 483}, {"name": "ss", "n": 417}],
            "funnel": {
                "raw": 55_149,
                "parsed": 11_076,
                "tcp": 6_208,
                "tls": 3_571,
                "config": 904,
                "http": 98,
            },
            "updated_utc": "16:29",
        },
        "pool": {
            "available": True,
            "generated_utc": "16:24",
            "total": 30_576,
            "by_protocol": {"http": 28_999, "socks4": 398, "socks5": 1_179},
            "grades": {
                "elite": 24_997,
                "anonymous": 449,
                "transparent": 658,
                "unknown": 4_472,
            },
            "median_ms": 127,
            "p95_ms": 5_671,
            "countries": 115,
            "cycle": {"parsed": 3_330_205, "unique": 753_682, "sampled": 3_000, "alive": 3_519},
            "sources_ok": 187,
            "sources_total": 194,
            "shards": 89,
            "files": {"http": 28_999, "socks4": 398, "socks5": 1_179, "all": 30_576, "ca": 12_271},
        },
        "proxy_rows": [
            {
                "rank": 1,
                "address": "45.85.119.124:80",
                "protocol": "http",
                "grade": "elite",
                "latency_ms": 7,
                "uptime_7d": 100,
                "country": "GB",
            },
            {
                "rank": 2,
                "address": "172.67.194.35:80",
                "protocol": "http",
                "grade": "anonymous",
                "latency_ms": 8,
                "uptime_7d": 99.5,
                "country": "CA",
            },
        ],
        "source_rows": [
            {
                "id": "gnxd3riftt2we-rh-http",
                "candidates": 23,
                "alive": 22,
                "live_rate": 95.7,
                "published": 500,
                "median_ms": 17,
                "elite_rate": 95.5,
            }
        ],
        "map_dots": [
            {"cc": "US", "n": 25, "x": 45.6, "y": 19.58, "r": 2.6, "halo": 5.8},
            {"cc": "DE", "n": 20, "x": 105.8, "y": 13.2, "r": 2.26, "halo": 0},
        ],
        "country_rows": [
            {"cc": "US", "n": 25, "width": 100.0},
            {"cc": "DE", "n": 20, "width": 80.0},
        ],
    }


def render_text(tmp_path: Path, text: str, data: dict | None = None) -> str:
    page = tmp_path / "index.html"
    page.write_text(text, encoding="utf-8")
    rendered = SiteRenderer(tmp_path).render("index.html", data if data is not None else payload(), "v1")
    assert rendered is not None
    return rendered


def block(name: str, fallback: str = "") -> str:
    return f"<!--begin:{name}-->{fallback}<!--end:{name}-->"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_numbers_are_formatted_for_people(tmp_path):
    data = payload()
    data["measure"] = {"float": 82.1, "trim": 100.0}
    out = render_text(
        tmp_path,
        "{{pool.total}}|{{measure.float}}|{{measure.trim}}|{{vpn.generation}}",
        data,
    )
    assert out == "30 576|82.1|100|gen-test"


def test_missing_tokens_use_fallback_or_an_em_dash(tmp_path):
    data = payload()
    data["flag"] = True
    data["empty"] = ""
    out = render_text(
        tmp_path,
        "{{nope}}|{{nope|нет данных}}|{{vpn.nope|типо}}|{{flag|да}}|{{empty|пусто}}",
        data,
    )
    assert out == "—|нет данных|типо|да|пусто"
    assert "{{" not in out


def test_unknown_token_never_survives_even_when_malformed(tmp_path):
    out = render_text(tmp_path, "{{vpn.unknown}} {{ broken", payload())
    assert "{{" not in out
    assert out.startswith("— ")


def test_values_and_fallbacks_are_html_escaped(tmp_path):
    data = payload()
    data["hostile"] = '<script>alert("x&y")</script>'
    out = render_text(
        tmp_path,
        "{{hostile}}|{{missing|<b>\"fallback\" & more</b>}}",
        data,
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;b&gt;&quot;fallback&quot; &amp; more&lt;/b&gt;" in out


def test_hostile_country_and_source_id_are_escaped_inside_blocks(tmp_path):
    data = payload()
    data["source_rows"][0]["id"] = '<script>"src"</script>'
    data["map_dots"] = [{"cc": '<b>"US"', "n": 5, "x": 1.234, "y": 2.345, "r": 0.9}]
    out = render_text(tmp_path, block("rows:sources") + block("map:dots"), data)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;b&gt;&quot;US&quot;" in out


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_proxy_rows_replace_the_block(tmp_path):
    data = payload()
    data["proxy_rows"] = data["proxy_rows"][:1]
    out = render_text(tmp_path, block("rows:proxy", "<tr><td>old</td></tr>"), data)
    assert out == (
        '<tr><td class="pa">1</td>'
        '<td class="addr">45.85.119.124:80</td>'
        '<td><span class="pb">HTTP</span></td>'
        '<td><span class="pb g-elite">elite</span></td>'
        '<td class="num">7 ms</td>'
        '<td class="up"><span class="upb"><i style="width:100%"></i></span>100%</td>'
        '<td class="num"><span class="ccx" data-cc="GB">GB</span></td></tr>'
    )


def test_source_rows_replace_the_block(tmp_path):
    out = render_text(tmp_path, block("rows:sources", "<tr><td>old</td></tr>"), payload())
    assert out.count("<tr>") == 1
    assert out.count("<td") == 8
    assert '<td class="addr">gnxd3riftt2we-rh-http</td>' in out
    assert '<td class="num">23</td><td class="num">22</td>' in out
    assert '<td class="num">95.7%</td>' in out
    assert '<td class="num">17 ms</td>' in out
    assert '<td class="num">95.5%</td>' in out
    assert '<span class="pb">500</span>' in out


def test_source_rates_are_fractions_and_missing_cells_are_dashes(tmp_path):
    data = payload()
    data["source_rows"] = [
        {
            "id": "fractional",
            "candidates": 10,
            "alive": 9,
            "live_rate": 0.9,
            "published": None,
            "median_ms": None,
            "elite_rate": 0.25,
        },
        {
            "id": "out-of-range",
            "candidates": None,
            "alive": None,
            "live_rate": 120,
            "published": None,
            "median_ms": 0,
            "elite_rate": -5,
        },
    ]
    out = render_text(tmp_path, block("rows:sources"), data)
    assert '<td class="num">90%</td>' in out
    assert '<td class="num">25%</td>' in out
    assert '<td class="num">—</td>' in out
    assert '<span class="pb">—</span>' in out
    assert "120%" not in out and "-5%" not in out
    assert "100%" in out and "0%" in out
    assert "— ms" not in out


def test_source_table_headers_match_cells_on_both_pages():
    for page in ("proxy.html", "en/proxy.html"):
        html = (SITE_DIR / page).read_text(encoding="utf-8")
        before, after = html.split("<!--begin:rows:sources-->", 1)
        rows = after.split("<!--end:rows:sources-->", 1)[0]
        heads = before.rsplit("<thead>", 1)[1].split("</thead>", 1)[0]
        assert heads.count("<th") == 8, page
        first_row = re.search(r"<tr>.*?</tr>", rows, re.S)
        assert first_row is not None, page
        assert first_row.group(0).count("<td") == 8, page
        assert ("топ-8" in html) if page == "proxy.html" else ("top 8" in html)


def test_protocol_bars_scale_to_the_largest_value(tmp_path):
    data = payload()
    data["vpn"]["protocols"] = [{"name": "vless", "n": 10}, {"name": "ss", "n": 5}]
    out = render_text(tmp_path, block("rows:protocols"), data)
    assert out.count('class="frow"') == 2
    assert '<span class="fl">vless</span>' in out
    assert '<i style="width:100%"></i>' in out
    assert '<span class="fl">ss</span>' in out
    assert '<i style="width:50%"></i>' in out
    assert '<span class="fv">10</span>' in out


def test_funnel_rows_have_six_stages_and_scale_from_raw(tmp_path):
    out = render_text(tmp_path, block("rows:funnel", '<div class="frow">old</div>'), payload())
    assert out.count('class="frow"') == 6
    for label in ("ИСТОЧНИКИ", "РАЗБОР", "TCP", "TLS", "КОНФИГ", "HTTP"):
        assert f'<span class="fl">{label}</span>' in out
    assert '<span class="fv">55 149</span>' in out
    assert '<span class="fv">11 076</span>' in out
    assert '<i style="width:100%"></i>' in out


def test_map_dots_get_a_halo_on_the_largest_dot(tmp_path):
    out = render_text(tmp_path, block("map:dots", "<circle/>"), payload())
    assert out.count('class="ms-dot"') == 2
    assert out.count('class="ms-halo"') == 1
    assert '<circle class="ms-halo" cx="45.60" cy="19.58" r="5.80"/>' in out
    assert '<circle class="ms-dot" style="fill:#38bdf8" cx="45.60" cy="19.58" r="2.60">' in out
    assert "<title>🇺🇸 US: 25</title>" in out
    assert "<title>🇩🇪 DE: 20</title>" in out


def test_empty_data_keeps_static_fallback_and_strips_markers(tmp_path):
    text = (
        block("rows:proxy", "<tr><td>static</td></tr>")
        + block("rows:funnel", '<div class="frow">static funnel</div>')
    )
    out = render_text(tmp_path, text, {})
    assert out == "<tr><td>static</td></tr>" + '<div class="frow">static funnel</div>'
    assert "<!--begin:" not in out
    assert "<!--end:" not in out


def test_unknown_blocks_are_left_alone(tmp_path):
    text = block("rows:future", "<p>keep</p>")
    out = render_text(tmp_path, text, payload())
    assert out == text


def test_render_does_not_mutate_data(tmp_path):
    data = payload()
    before = copy.deepcopy(data)
    render_text(tmp_path, block("rows:proxy") + "{{pool.total}}", data)
    assert data == before


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_is_keyed_by_mtime_and_version(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("a={{vpn.verified|0}}", encoding="utf-8")
    renderer = SiteRenderer(tmp_path)

    first = renderer.render("index.html", payload(), "v1")
    assert first == "a=150"
    assert renderer.render("index.html", payload(), "v1") is first

    stat = page.stat()
    page.write_text("b={{vpn.verified|0}}", encoding="utf-8")
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert renderer.render("index.html", payload(), "v2") == "b=150"

    stat = page.stat()
    page.write_text("c={{vpn.verified|0}}", encoding="utf-8")
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert renderer.render("index.html", payload(), "v2") == "c=150"


def test_missing_page_is_none(tmp_path):
    assert SiteRenderer(tmp_path).render("missing.html", payload(), "v1") is None


# ---------------------------------------------------------------------------
# The real pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["index.html", "proxy.html", "verify.html", "status.html"])
def test_real_pages_render_without_tokens_or_block_markers(page):
    rendered = SiteRenderer(SITE_DIR).render(page, payload(), "fixture-v1")
    assert rendered is not None
    assert "{{" not in rendered, page
    assert "<!--begin:" not in rendered, page
    assert "<!--end:" not in rendered, page


def test_index_map_block_replaces_every_static_dot():
    rendered = SiteRenderer(SITE_DIR).render("index.html", payload(), "fixture-v1")
    assert rendered is not None
    assert "<title>🇩🇪 DE: 20</title>" in rendered
    assert "<title>🇸🇬 SG: 6</title>" not in rendered


def test_secondary_text_meets_contrast_and_table_headers_are_legible():
    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(a: str, b: str) -> float:
        high, low = sorted((luminance(a), luminance(b)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    css = (SITE_DIR / "system.css").read_text(encoding="utf-8")
    dim = re.search(r"--dim:(#[0-9a-fA-F]{6})", css).group(1)
    bg = re.search(r"--bg:(#[0-9a-fA-F]{6})", css).group(1)
    s1 = re.search(r"--s1:(#[0-9a-fA-F]{6})", css).group(1)
    assert contrast(dim, bg) >= 4.5
    assert contrast(dim, s1) >= 4.5
    size = re.search(r"\.pt th\{[^}]*font-size:([0-9.]+)rem", css).group(1)
    assert float(size) >= 0.75
