"""Field-guide enrichment for species records (FLEDGE Phase 6).

Fills in the data that makes the Species Library read like a field guide rather
than a bare name list:

* ``wiki_url`` + ``description`` — Wikipedia REST summary. Both come from the
  *same* request, so the description is effectively free once we're already
  looking up the URL.
* ``family`` (and ``order_name`` when missing) — GBIF's taxonomy match. Free,
  keyless, no registration.

Runs as a fire-and-forget background task on first sighting of a species and
writes only fields that are still empty, so a manually curated value is never
overwritten. Every field is optional: an unenriched species must still render.

Conservation status is deliberately not fetched — the IUCN Red List API
requires a registered key, and GBIF's threat status is sparse for common
backyard birds, so it would mostly render as "unknown".
"""
import logging

import aiohttp

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=8)
_GBIF_MATCH = "https://api.gbif.org/v1/species/match"

# Wikipedia extracts can be several paragraphs; the library shows a blurb.
MAX_DESCRIPTION_CHARS = 600


def _truncate(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    # Prefer cutting at a sentence boundary so the blurb doesn't end mid-word.
    cut = text[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


async def fetch_wikipedia_summary(query: str) -> dict:
    """Return ``{"url": ..., "description": ...}`` for a Wikipedia page query.

    Missing keys mean the lookup failed or the page had no extract; callers
    treat enrichment as best-effort.
    """
    slug = query.replace(" ", "_")
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
    except Exception:
        logger.debug("Wikipedia summary lookup failed for %r", query, exc_info=True)
        return {}

    # Disambiguation pages describe the page, not the bird — skip them.
    if data.get("type") == "disambiguation":
        return {}

    result: dict = {}
    url = data.get("content_urls", {}).get("desktop", {}).get("page")
    if url:
        result["url"] = url
    extract = (data.get("extract") or "").strip()
    if extract:
        result["description"] = _truncate(extract)
    return result


async def fetch_gbif_taxonomy(scientific_name: str) -> dict:
    """Return ``{"family": ..., "order": ...}`` from GBIF's name match."""
    if not scientific_name.strip():
        return {}
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                _GBIF_MATCH, params={"name": scientific_name, "strict": "false"}
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
    except Exception:
        logger.debug("GBIF lookup failed for %r", scientific_name, exc_info=True)
        return {}

    # matchType NONE means GBIF couldn't resolve the name at all.
    if data.get("matchType") in (None, "NONE"):
        return {}

    result = {}
    if data.get("family"):
        result["family"] = data["family"]
    if data.get("order"):
        result["order"] = data["order"]
    return result


async def gather_enrichment(common_name: str, scientific_name: str) -> dict:
    """Best-effort enrichment payload for a species. Never raises."""
    summary = await fetch_wikipedia_summary(scientific_name)
    if not summary.get("description"):
        # Scientific name often redirects to a stub; the common name usually
        # lands on the article with the real extract. Keep whichever fields the
        # scientific-name lookup did produce.
        fallback = await fetch_wikipedia_summary(f"{common_name} bird")
        summary = {**fallback, **summary}

    wiki_url = summary.get("url")
    if not wiki_url:
        # Reuse the existing three-step chain (API → search → constructed URL
        # verified with HEAD) rather than duplicating it here.
        from ..notifications.wikipedia import lookup_wiki_url

        wiki_url = await lookup_wiki_url(common_name, scientific_name)

    taxonomy = await fetch_gbif_taxonomy(scientific_name)

    return {
        "wiki_url": wiki_url,
        "description": summary.get("description"),
        "family": taxonomy.get("family"),
        "order_name": taxonomy.get("order"),
    }


async def enrich_species(species_id: int, common_name: str, scientific_name: str) -> None:
    """Background task: cache field-guide data, filling only empty columns."""
    from sqlalchemy import select

    from ..database.connection import get_session_factory
    from ..database.models import Species

    data = await gather_enrichment(common_name, scientific_name)
    if not any(data.values()):
        logger.debug("No enrichment found for %r", common_name)
        return

    try:
        async with get_session_factory()() as db:
            async with db.begin():
                sp = (
                    await db.execute(select(Species).where(Species.id == species_id))
                ).scalar_one_or_none()
                if sp is None:
                    return
                filled = []
                for field, value in data.items():
                    if value and getattr(sp, field, None) in (None, ""):
                        setattr(sp, field, value)
                        filled.append(field)
                if filled:
                    logger.info("Enriched species %r: %s", common_name, ", ".join(filled))
    except Exception:
        logger.exception("Failed to persist enrichment for species %d", species_id)
