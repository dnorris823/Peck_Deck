import logging

import aiohttp

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=8)


async def lookup_wiki_url(common_name: str, scientific_name: str) -> str | None:
    """Try three methods in order; return the first URL that resolves."""
    for query in (scientific_name, f"{common_name} bird"):
        url = await _api_lookup(query)
        if url:
            return url

    # Fallback: construct the standard Wikipedia URL and verify it responds
    slug = common_name.replace(" ", "_")
    candidate = f"https://en.wikipedia.org/wiki/{slug}"
    if await _head_ok(candidate):
        return candidate

    return None


async def _api_lookup(query: str) -> str | None:
    slug = query.replace(" ", "_")
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return (
                        data.get("content_urls", {})
                        .get("desktop", {})
                        .get("page")
                    )
    except Exception:
        pass
    return None


async def _head_ok(url: str) -> bool:
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.head(url) as resp:
                return resp.status == 200
    except Exception:
        return False


async def update_species_wiki_url(species_id: int, common_name: str, scientific_name: str) -> None:
    """Background task: look up the Wikipedia URL and write it to the DB if still missing."""
    from sqlalchemy import select

    from ..database.connection import get_session_factory
    from ..database.models import Species

    url = await lookup_wiki_url(common_name, scientific_name)
    if not url:
        logger.debug("No Wikipedia URL found for '%s'", common_name)
        return

    try:
        async with get_session_factory()() as db:
            async with db.begin():
                result = await db.execute(select(Species).where(Species.id == species_id))
                sp = result.scalar_one_or_none()
                if sp is not None and sp.wiki_url is None:
                    sp.wiki_url = url
                    logger.info("Wikipedia URL saved for '%s': %s", common_name, url)
    except Exception:
        logger.exception("Failed to save Wikipedia URL for species %d", species_id)
