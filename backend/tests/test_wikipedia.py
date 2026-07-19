"""Tests for the Wikipedia URL lookup fallback chain (PRD §9.1).

``lookup_wiki_url`` tries, in order:
  1. REST summary API on the scientific name,
  2. REST summary API on ``"{common} bird"``,
  3. a constructed ``/wiki/{Common_Name}`` URL verified with a HEAD request,
  4. and finally gives up with ``None``.

We patch the two network primitives (``_api_lookup`` / ``_head_ok``) so the
chain's ordering and short-circuiting are asserted without any HTTP traffic.
``update_species_wiki_url`` is then exercised against the real test DB.
"""
import asyncio
import secrets

from backend.database.connection import get_session_factory
from backend.database.models import Species
from backend.notifications import wikipedia as wiki


def _patch_chain(monkeypatch, *, api_results: dict, head_ok: bool):
    """api_results maps a query string -> URL (or None); anything unlisted -> None."""
    calls = {"api": [], "head": []}

    async def fake_api(query):
        calls["api"].append(query)
        return api_results.get(query)

    async def fake_head(url):
        calls["head"].append(url)
        return head_ok

    monkeypatch.setattr(wiki, "_api_lookup", fake_api)
    monkeypatch.setattr(wiki, "_head_ok", fake_head)
    return calls


def test_scientific_name_api_hit_wins_first(monkeypatch):
    calls = _patch_chain(
        monkeypatch,
        api_results={"Cardinalis cardinalis": "https://en.wikipedia.org/wiki/Northern_Cardinal"},
        head_ok=False,
    )
    url = asyncio.run(wiki.lookup_wiki_url("Northern Cardinal", "Cardinalis cardinalis"))
    assert url == "https://en.wikipedia.org/wiki/Northern_Cardinal"
    # Short-circuits on the first (scientific-name) lookup — no second query, no HEAD.
    assert calls["api"] == ["Cardinalis cardinalis"]
    assert calls["head"] == []


def test_common_name_api_used_when_scientific_misses(monkeypatch):
    calls = _patch_chain(
        monkeypatch,
        api_results={"Blue Jay bird": "https://en.wikipedia.org/wiki/Blue_jay"},
        head_ok=False,
    )
    url = asyncio.run(wiki.lookup_wiki_url("Blue Jay", "Cyanocitta cristata"))
    assert url == "https://en.wikipedia.org/wiki/Blue_jay"
    # Falls through scientific name to the "{common} bird" query.
    assert calls["api"] == ["Cyanocitta cristata", "Blue Jay bird"]
    assert calls["head"] == []


def test_constructed_url_used_when_api_fails_but_head_ok(monkeypatch):
    calls = _patch_chain(monkeypatch, api_results={}, head_ok=True)
    url = asyncio.run(wiki.lookup_wiki_url("House Wren", "Troglodytes aedon"))
    assert url == "https://en.wikipedia.org/wiki/House_Wren"
    # Both API queries tried, then the constructed slug verified via HEAD.
    assert calls["api"] == ["Troglodytes aedon", "House Wren bird"]
    assert calls["head"] == ["https://en.wikipedia.org/wiki/House_Wren"]


def test_returns_none_when_every_method_fails(monkeypatch):
    calls = _patch_chain(monkeypatch, api_results={}, head_ok=False)
    url = asyncio.run(wiki.lookup_wiki_url("Ghost Bird", "Nullus avis"))
    assert url is None
    assert calls["api"] == ["Nullus avis", "Ghost Bird bird"]
    assert calls["head"] == ["https://en.wikipedia.org/wiki/Ghost_Bird"]


# ---------------------------------------------------------------------------
# update_species_wiki_url — the background backfill that writes the result
# ---------------------------------------------------------------------------
async def _mk_species(wiki_url=None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(
                common_name=f"WikiBird {secrets.token_hex(3)}",
                genus="Genus", species_name="species", wiki_url=wiki_url,
            )
            db.add(sp)
            await db.flush()
            return sp.id


async def _get_wiki_url(species_id: int) -> str | None:
    from sqlalchemy import select
    async with get_session_factory()() as db:
        sp = (await db.execute(select(Species).where(Species.id == species_id))).scalar_one()
        return sp.wiki_url


def test_update_backfills_missing_url(client, monkeypatch):
    _patch_chain(monkeypatch, api_results={"Genus species": "https://en.wikipedia.org/wiki/Found"}, head_ok=False)
    spid = asyncio.run(_mk_species(wiki_url=None))

    asyncio.run(wiki.update_species_wiki_url(spid, "Genus species", "Genus species"))

    assert asyncio.run(_get_wiki_url(spid)) == "https://en.wikipedia.org/wiki/Found"


def test_update_does_not_overwrite_existing_url(client, monkeypatch):
    existing = "https://en.wikipedia.org/wiki/Already_Set"
    _patch_chain(monkeypatch, api_results={"Genus species": "https://en.wikipedia.org/wiki/Different"}, head_ok=False)
    spid = asyncio.run(_mk_species(wiki_url=existing))

    asyncio.run(wiki.update_species_wiki_url(spid, "Genus species", "Genus species"))

    # A URL already on the row is left untouched.
    assert asyncio.run(_get_wiki_url(spid)) == existing


def test_update_noop_when_lookup_returns_none(client, monkeypatch):
    _patch_chain(monkeypatch, api_results={}, head_ok=False)
    spid = asyncio.run(_mk_species(wiki_url=None))

    asyncio.run(wiki.update_species_wiki_url(spid, "Genus species", "Genus species"))

    assert asyncio.run(_get_wiki_url(spid)) is None
