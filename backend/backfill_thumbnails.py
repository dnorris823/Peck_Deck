"""Make thumbnails for sightings stored before uploads made them.

Run from the repo root, or inside the api container:

    python -m backend.backfill_thumbnails
    docker compose exec api python -m backend.backfill_thumbnails

Uses ``settings.DATABASE_URL``. Safe to stop and run again. It only picks rows
with an image and no thumbnail, and it commits after every batch.

A row whose image Pillow cannot decode keeps a null thumbnail, and the image
route serves its full image instead. The script walks rows in id order, so such
a row is tried once per run and never loops.
"""
import argparse
import asyncio
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from sqlalchemy import select, update

from .config import settings
from .database.connection import dispose_db, get_session_factory, init_db
from .database.models import Sighting
from .sightings.thumbnails import make_thumbnail

DEFAULT_BATCH_SIZE = 200


async def backfill(batch_size: int = DEFAULT_BATCH_SIZE, workers: int | None = None) -> tuple[int, int]:
    """Fill ``thumbnail_data`` for every row that lacks one.

    Returns ``(made, failed)``. Each batch reads at most ``batch_size`` images,
    so memory stays flat whatever the table size. Decoding runs in a process
    pool, because it is CPU bound and the GIL would serialise threads.
    """
    made = failed = 0
    last_id = 0
    loop = asyncio.get_running_loop()
    factory = get_session_factory()

    with ProcessPoolExecutor(max_workers=workers) as pool:
        while True:
            async with factory() as db:
                async with db.begin():
                    rows = (
                        await db.execute(
                            select(Sighting.id, Sighting.image_data)
                            .where(
                                Sighting.id > last_id,
                                Sighting.image_data.is_not(None),
                                Sighting.thumbnail_data.is_(None),
                            )
                            .order_by(Sighting.id)
                            .limit(batch_size)
                        )
                    ).all()
                    if not rows:
                        break
                    last_id = rows[-1].id

                    thumbs = await asyncio.gather(
                        *(loop.run_in_executor(pool, make_thumbnail, row.image_data) for row in rows)
                    )
                    # A list of dicts keyed by primary key makes this one
                    # executemany UPDATE for the whole batch.
                    updates = [
                        {"id": row.id, "thumbnail_data": thumb}
                        for row, thumb in zip(rows, thumbs)
                        if thumb is not None
                    ]
                    failed += len(rows) - len(updates)
                    if updates:
                        await db.execute(update(Sighting), updates)
                    made += len(updates)
            print(f"  up to id {last_id}: {made} made, {failed} could not decode", flush=True)

    return made, failed


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=None, help="decode processes, default one per CPU")
    args = parser.parse_args(argv)

    init_db(settings.DATABASE_URL)
    started = time.perf_counter()
    try:
        made, failed = await backfill(args.batch_size, args.workers)
    finally:
        await dispose_db()
    print(f"Done in {time.perf_counter() - started:.1f}s: {made} thumbnails made, {failed} could not decode.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
