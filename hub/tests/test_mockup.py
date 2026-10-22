"""Макет не должен расходиться с продуктом.

Прежний макет был рукописной копией страниц: та же палитра, те же таблицы, те
же классы, набранные заново. Первый же его абзац признавал проблему («если
разойдутся — макет начнёт врать»), и она реализовалась: палитра разъехалась на
пять копий, а `--danger` пропал ровно потому, что копий было пять.

Теперь макет собирает `scripts/build_mockup.py` из самих файлов `src/hub/ui/`,
и копий в нём нет. Проверять поэтому нужно не «цвет правильный», а две вещи:

* **файл не устарел.** Если страницу поправили, а макет не пересобрали, макет
  показывает то, чего больше нет, — и это ровно тот случай, когда он врёт;
* **макет не размножил палитру.** Соблазн набрать цвета оболочки руками возникнет
  снова, и тест должен его ловить.

Что эти тесты *не* делают: они не проверяют, что макет красиво выглядит.
Скриншот нельзя утвердить ассертом, и попытка превратила бы тест в описание
того, как он выглядел в день, когда его писали.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "hub" / "ui"
MOCKUP = ROOT / "docs" / "design" / "mockup.html"
FIXTURES = ROOT / "docs" / "design" / "fixtures"
BUILDER = ROOT / "scripts" / "build_mockup.py"


@pytest.fixture(scope="module")
def mockup() -> str:
    if not MOCKUP.is_file():
        pytest.fail(f"{MOCKUP} отсутствует — запустите scripts/build_mockup.py")
    return MOCKUP.read_text(encoding="utf-8")


def _frames(mockup: str) -> list[str]:
    """Разэкранированное содержимое всех `srcdoc`."""
    return [html.unescape(f) for f in re.findall(r'srcdoc="([^"]*)"', mockup)]


def test_the_mockup_is_not_stale():
    """Собранный файл совпадает с тем, что даёт генератор сейчас.

    Это главный тест. Он падает, когда страницу поправили, а макет не
    пересобрали, — то есть именно тогда, когда макет начинает врать.
    """
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        f"макет устарел — запустите scripts/build_mockup.py\n{result.stdout}{result.stderr}"
    )


def test_the_mockup_shows_every_surface(mockup):
    """Каждая страница продукта присутствует в макете.

    Список берётся из самих файлов, а не из литерала: страница, которую
    добавили и забыли показать, должна ломать тест, а не молча отсутствовать.

    Опознаётся страница по заголовку `<title>` — он у каждой свой, и в отличие
    от имени файла он не исчезнет при инлайне. Имя файла осталось бы только в
    `data-from` у ресурсов, а страницы туда не попадают: они едут в `srcdoc`.
    """
    surfaces = sorted(p.name for p in UI.glob("*.html"))
    assert surfaces, "в src/hub/ui нет ни одной страницы"

    shown = set()
    for frame in _frames(mockup):
        title = re.search(r"<title[^>]*>(.*?)</title>", frame, re.DOTALL)
        if title:
            shown.add(title.group(1).strip())

    for name in surfaces:
        title = re.search(
            r"<title[^>]*>(.*?)</title>", (UI / name).read_text(encoding="utf-8"), re.DOTALL
        )
        assert title, f"{name} без <title> — макет не сможет его опознать"
        assert title.group(1).strip() in shown, (
            f"{name} не показан в макете (искали <title> {title.group(1).strip()!r})"
        )


def test_the_mockup_inlines_every_asset(mockup):
    """Стили и скрипты вложены, а не оставлены ссылкой на `/static/`.

    Макет открывают из `file://`, где `/static/` не ведёт никуда. Ссылка,
    оставшаяся внешней, выглядит в разметке правильно и не работает — то есть
    ломается молча, ровно как ломался `--danger`.

    Проверяются именно ссылки (`href`/`src`), а не любые упоминания: путь
    встречается и в комментариях — например, `hub.css` объясняет, что подключён
    как `/static/hub.css`. Запрещать это значило бы запретить объяснять связь.
    """
    for frame in _frames(mockup):
        leftovers = re.findall(r'(?:href|src)="/static/[\w.-]+"', frame)
        assert not leftovers, (
            f"в рамке осталась внешняя ссылка {leftovers} — из file:// она не загрузится"
        )
        # Каждая страница подключала base.css, и он должен быть вложен.
        assert 'data-from="base.css"' in frame, "base.css не вложен в рамку"


def test_the_mockup_carries_no_new_palette(mockup):
    """В макете нет ни одного цвета, которого нет в `base.css`.

    Соблазн набрать цвета оболочки руками возникнет снова — и это была бы
    шестая копия палитры, с той же судьбой, что и первые пять. Тест смотрит на
    оболочку (рамки, подписи, блок ошибок), потому что содержимое рамок — это
    сами страницы, и их цвета уже проверяет `test_palette.py`.
    """
    base = (UI / "base.css").read_text(encoding="utf-8")
    declared = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", base)}

    # Вне `<iframe ...>` — то есть разметка и стиль самой оболочки.
    shell = re.sub(r'srcdoc="[^"]*"', "", mockup)
    shell = re.sub(r"<style>.*?</style>", lambda m: m.group(0), shell, flags=re.DOTALL)

    # Оболочке разрешено ровно одно собственное значение: чёрный, к которому
    # подмешивается фон страниц. Это не цвет продукта, а отсутствие цвета.
    allowed = declared | {"#000000"}

    found = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", shell)}
    extra = sorted(found - allowed)
    assert not extra, (
        "в оболочке макета появились цвета вне base.css — это ещё одна копия палитры: "
        + ", ".join(extra)
    )


def test_the_mockup_makes_no_external_request(mockup):
    """Ни одного внешнего адреса.

    Макет должен открываться из `file://` без сети. Внешний запрос здесь —
    не только утечка: он делает файл неоткрываемым на машине без интернета, а
    именно так его и смотрят.
    """
    for pattern in (r'src="https?://', r'href="https?://(?!/)', r"@import\s+url\(https?://"):
        found = re.findall(pattern, mockup)
        assert not found, f"макет тянет что-то извне: {found[:3]}"


def test_the_fixtures_carry_no_addresses_or_tokens():
    """Снимки не содержат ни IP узлов, ни токенов, ни секретов.

    Макет публикуется вместе с репозиторием, а снимки — его часть. Публичный
    ответ сервера адресов не отдаёт по построению; это проверка, что так оно и
    осталось, и что в снимок не попал секрет оператора.
    """
    if not FIXTURES.is_dir():
        pytest.skip("нет каталога со снимками")

    leaked: list[str] = []
    for path in sorted(FIXTURES.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        # Публичные адреса и голые IPv4, которыми хаб отдаёт узлы.
        for ip in re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text):
            if not ip.startswith(("127.", "0.", "255.")):
                leaked.append(f"{path.name}: {ip}")
        if "HUB_BOT_SECRET" in text:
            leaked.append(f"{path.name}: HUB_BOT_SECRET")
    assert not leaked, "снимок для макета содержит то, чего в нём быть не должно:\n" + "\n".join(
        leaked
    )


def test_the_admin_fixture_has_the_shape_the_panel_draws():
    """Снимок панели пригоден для отрисовки, а не просто валидный JSON.

    Панель рисует `d.pool`, `d.sources`, `d.generations`, `d.tokens`, `d.funnel`.
    Снимок без них дал бы пустую панель, и макет показывал бы ошибку чтения —
    то есть не продукт.
    """
    import json

    path = FIXTURES / "admin.json"
    if not path.is_file():
        pytest.skip("нет снимка панели")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) >= {"pool", "sources", "generations", "tokens", "health"}
    assert isinstance(data["pool"], dict)
    assert "by_country" in data["pool"], "панель рисует страны из pool.by_country"


# --- маршрут `/mockup` ---------------------------------------------------
#
# Макет отдаёт сам хаб, потому что посмотреть его надо с телефона или с
# машины без шелла: `scp` и SSH-туннель требуют шелла, а он есть не всегда.
# Это делает макет достижимым по той же ссылке на IP, что и подписка, — и
# значит, у него появляется поверхность, которую надо удержать.


def _client(tmp_path, monkeypatch, mockup: Path | None):
    """Приложение с макетом по указанному пути (или с несуществующим)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "src"))
    from hub.api import create_app
    from hub.store import Store

    if mockup is None:
        monkeypatch.setenv("HUB_MOCKUP", str(tmp_path / "нет-такого.html"))
    else:
        monkeypatch.setenv("HUB_MOCKUP", str(mockup))
    store = Store(tmp_path / "state")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(store=store, sources={}))


def test_the_api_serves_the_built_mockup(tmp_path, monkeypatch):
    """Собранный макет отдаётся и совпадает с файлом побайтно.

    Не «похож»: макет — это то, что проверяют глазами, и подменённый
    заголовок или потерянный кадр заметить в браузере нельзя.
    """
    api = _client(tmp_path, monkeypatch, MOCKUP)
    response = api.get("/mockup")
    assert response.status_code == 200
    assert response.content == MOCKUP.read_bytes()
    assert response.headers["content-type"].startswith("text/html")


def test_the_served_mockup_is_noindex(tmp_path, monkeypatch):
    """Ни `<meta robots>`, ни заголовка недостаточно по отдельности.

    Макет показывает панель оператора нарисованной. В выдаче поисковика это
    выглядело бы как настоящая панель со настоящими ключами. Мета-тег читают
    движки, которые разбирают HTML; заголовок — те, кто смотрит только на
    заголовки. Нужны оба.
    """
    api = _client(tmp_path, monkeypatch, MOCKUP)
    response = api.get("/mockup")
    assert "noindex" in response.headers.get("x-robots-tag", "")
    body = response.content.decode("utf-8")
    assert 'name="robots"' in body and "noindex" in body


def test_a_missing_mockup_is_404_not_an_empty_sheet(tmp_path, monkeypatch):
    """Чекаут без `docs/` — законная установка, а не поломка.

    Пустой специмен-лист читался бы как сломанный дизайн. 404 с указанием,
    что запустить, — это то, что человек может выполнить.
    """
    api = _client(tmp_path, monkeypatch, None)
    response = api.get("/mockup")
    assert response.status_code == 404
    assert "build_mockup" in response.text


def test_the_mockup_route_is_not_the_operator_panel(tmp_path, monkeypatch):
    """Макет открыт снаружи, панель — нет. Это разные поверхности.

    Регрессия на соблазн «раз уж статика, отдадим и панель»: макет — это
    картинка панели, а `/admin/data` — сами данные. Первое можно всем,
    второе — никому снаружи.
    """
    api = _client(tmp_path, monkeypatch, MOCKUP)
    assert api.get("/mockup").status_code == 200
    assert api.get("/admin/data").status_code in (403, 404)


# --- маршрут `/design/` --------------------------------------------------
#
# Два направления открываются по той же причине, что и `/mockup`: дизайн
# судят с телефона, а не с шелла. Но у этой поверхности есть свой риск —
# каталог, из которого она читает, лежит рядом с `fixtures/` и `src/`, где
# никакого запрета на выдачу нет. Поэтому проверяется не «отдаёт файл», а
# «отдаёт только то, что перечислено, и ничего за пределами каталога».


def _design_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "src"))
    from hub.api import create_app
    from hub.store import Store

    monkeypatch.setenv("HUB_DESIGN", str(ROOT / "docs" / "design"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(store=Store(tmp_path / "state"), sources={}))


def test_the_design_sheet_and_its_parts_are_served(tmp_path, monkeypatch):
    """Корень — лист для оценки; рядом лежат страницы, стили и шрифты.

    Без шрифтов страница откроется системной гарнитурой и покажет не тот
    дизайн, который оценивают, — поэтому `.woff2` в списке разрешённых
    типов, а не только `.html`.
    """
    api = _design_client(tmp_path, monkeypatch)
    for path, kind in (
        ("/design/", "text/html"),
        ("/design/pages/a-1-free.html", "text/html"),
        ("/design/pages/b.css", "text/css"),
        ("/design/assets/fonts/literata-latin.woff2", "font/woff2"),
    ):
        response = api.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith(kind), path
        assert "noindex" in response.headers.get("x-robots-tag", ""), path


def test_the_design_route_refuses_its_own_sources(tmp_path, monkeypatch):
    """`src/`, `fixtures/` и всё остальное вне allow-list — 404.

    Каталог дизайна держит рядом исходники и снимки данных. Маршрут,
    который отдаёт «любой файл из docs/design», отдал бы и их — не потому,
    что они секретны, а потому, что это поверхность, которую никто не
    собирался открывать.
    """
    api = _design_client(tmp_path, monkeypatch)
    for path in (
        "/design/src/data.py",
        "/design/fixtures/stats.json",
        "/design/src/worldpath.py",
    ):
        assert api.get(path).status_code == 404, path


def test_the_design_route_cannot_walk_out_of_its_directory(tmp_path, monkeypatch):
    """Ни `..`, ни закодированный `%2e%2e`, ни абсолютный путь не выходят наружу.

    Проверка идёт по разрешённому пути, а не по строке запроса: `Path.resolve`
    снимает `..` и симлинки до сравнения с корнем, поэтому обход не зависит от
    того, в каком виде клиент его прислал.
    """
    api = _design_client(tmp_path, monkeypatch)
    for path in (
        "/design/../fixtures/stats.json",
        "/design/pages/../../fixtures/stats.json",
        "/design/%2e%2e/fixtures/stats.json",
        "/design//etc/passwd",
    ):
        assert api.get(path).status_code == 404, path
