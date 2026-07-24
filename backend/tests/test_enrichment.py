"""Species field-guide enrichment (FLEDGE Phase 6).

Network calls are stubbed at the module boundary — these assert the merge,
truncation, and fill-only-empty-columns rules, not Wikipedia's or GBIF's
behaviour.
"""
import asyncio
import secrets

import pytest
from sqlalchemy import select

from backend.database.connection import get_session_factory
from backend.database.models import Species
from backend.species import enrichment


def _mk_species(**kwargs) -> int:
    async def _create():
        async with get_session_factory()() as db:
            async with db.begin():
                sp = Species(
                    common_name=f"Enrich Bird {secrets.token_hex(3)}",
                    genus="Testus",
                    species_name="enrichus",
                    **kwargs,
                )
                db.add(sp)
                await db.flush()
                return sp.id

    return asyncio.run(_create())


def _read(species_id: int) -> Species:
    async def _get():
        async with get_session_factory()() as db:
            return (
                await db.execute(select(Species).where(Species.id == species_id))
            ).scalar_one()

    return asyncio.run(_get())


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------
def test_short_description_is_left_alone():
    assert enrichment._truncate("A small red bird.") == "A small red bird."


def test_long_description_is_cut_at_a_sentence_boundary():
    text = ("The cardinal is a songbird. " * 40).strip()

    result = enrichment._truncate(text)

    assert len(result) <= enrichment.MAX_DESCRIPTION_CHARS
    assert result.endswith("."), "should cut on a sentence, not mid-word"


def test_description_without_sentences_is_ellipsised():
    result = enrichment._truncate("word " * 400)

    assert len(result) <= enrichment.MAX_DESCRIPTION_CHARS + 1
    assert result.endswith("…")


def test_whitespace_is_normalised():
    assert enrichment._truncate("a\n\n  b\tc") == "a b c"


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------
def test_gather_merges_wikipedia_and_gbif(monkeypatch):
    async def fake_summary(query):
        return {"url": "https://en.wikipedia.org/wiki/Test", "description": "A test bird."}

    async def fake_gbif(name):
        return {"family": "Cardinalidae", "order": "Passeriformes"}

    monkeypatch.setattr(enrichment, "fetch_wikipedia_summary", fake_summary)
    monkeypatch.setattr(enrichment, "fetch_gbif_taxonomy", fake_gbif)

    data = asyncio.run(enrichment.gather_enrichment("Test Bird", "Testus enrichus"))

    assert data == {
        "wiki_url": "https://en.wikipedia.org/wiki/Test",
        "description": "A test bird.",
        "family": "Cardinalidae",
        "order_name": "Passeriformes",
    }


def test_gather_survives_both_sources_failing(monkeypatch):
    async def empty(*_a, **_k):
        return {}

    async def no_url(*_a, **_k):
        return None

    monkeypatch.setattr(enrichment, "fetch_wikipedia_summary", empty)
    monkeypatch.setattr(enrichment, "fetch_gbif_taxonomy", empty)
    monkeypatch.setattr(
        "backend.notifications.wikipedia.lookup_wiki_url", no_url
    )

    data = asyncio.run(enrichment.gather_enrichment("Test Bird", "Testus enrichus"))

    assert not any(data.values())


def test_gather_falls_back_to_the_common_name_for_a_description(monkeypatch):
    calls = []

    async def fake_summary(query):
        calls.append(query)
        if query == "Testus enrichus":
            return {"url": "https://en.wikipedia.org/wiki/Stub"}  # no extract
        return {"url": "https://en.wikipedia.org/wiki/Real", "description": "Real blurb."}

    async def empty(*_a, **_k):
        return {}

    monkeypatch.setattr(enrichment, "fetch_wikipedia_summary", fake_summary)
    monkeypatch.setattr(enrichment, "fetch_gbif_taxonomy", empty)

    data = asyncio.run(enrichment.gather_enrichment("Test Bird", "Testus enrichus"))

    assert calls == ["Testus enrichus", "Test Bird bird"]
    assert data["description"] == "Real blurb."
    # The scientific-name lookup's URL wins — it's the more precise match.
    assert data["wiki_url"] == "https://en.wikipedia.org/wiki/Stub"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _patch_gather(monkeypatch, payload):
    async def fake(*_a, **_k):
        return payload

    monkeypatch.setattr(enrichment, "gather_enrichment", fake)


def test_enrichment_fills_empty_columns(client, monkeypatch):
    species_id = _mk_species()
    _patch_gather(
        monkeypatch,
        {
            "wiki_url": "https://en.wikipedia.org/wiki/X",
            "description": "Blurb.",
            "family": "Cardinalidae",
            "order_name": "Passeriformes",
        },
    )

    asyncio.run(enrichment.enrich_species(species_id, "Test Bird", "Testus enrichus"))

    sp = _read(species_id)
    assert sp.wiki_url == "https://en.wikipedia.org/wiki/X"
    assert sp.description == "Blurb."
    assert sp.family == "Cardinalidae"
    assert sp.order_name == "Passeriformes"


def test_enrichment_never_overwrites_existing_values(client, monkeypatch):
    """A curated value must survive a later background refresh."""
    species_id = _mk_species(
        wiki_url="https://curated.example/bird", description="Hand-written."
    )
    _patch_gather(
        monkeypatch,
        {
            "wiki_url": "https://en.wikipedia.org/wiki/Auto",
            "description": "Automatic.",
            "family": "Cardinalidae",
            "order_name": None,
        },
    )

    asyncio.run(enrichment.enrich_species(species_id, "Test Bird", "Testus enrichus"))

    sp = _read(species_id)
    assert sp.wiki_url == "https://curated.example/bird"
    assert sp.description == "Hand-written."
    assert sp.family == "Cardinalidae", "empty columns should still be filled"


def test_enrichment_is_a_noop_when_nothing_is_found(client, monkeypatch):
    species_id = _mk_species()
    _patch_gather(
        monkeypatch,
        {"wiki_url": None, "description": None, "family": None, "order_name": None},
    )

    asyncio.run(enrichment.enrich_species(species_id, "Test Bird", "Testus enrichus"))

    sp = _read(species_id)
    assert sp.wiki_url is None and sp.description is None and sp.family is None


def test_enrichment_survives_a_missing_species(client, monkeypatch):
    """Fire-and-forget: a deleted species must not raise out of the task."""
    _patch_gather(monkeypatch, {"wiki_url": "https://x.test", "description": None,
                                "family": None, "order_name": None})

    asyncio.run(enrichment.enrich_species(9_999_999, "Gone", "Gone gone"))


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"matchType": "NONE"}, {}),
        ({"matchType": "EXACT", "family": "Corvidae"}, {"family": "Corvidae"}),
        (
            {"matchType": "FUZZY", "family": "Corvidae", "order": "Passeriformes"},
            {"family": "Corvidae", "order": "Passeriformes"},
        ),
    ],
)
def test_gbif_match_handling(monkeypatch, payload, expected):
    class _Resp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return payload

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def get(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr(enrichment.aiohttp, "ClientSession", lambda *a, **k: _Session())

    assert asyncio.run(enrichment.fetch_gbif_taxonomy("Testus enrichus")) == expected
