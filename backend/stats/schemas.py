from dataclasses import dataclass


@dataclass
class SpeciesCountResponse:
    id: int
    common_name: str
    genus: str
    species_name: str
    order_name: str | None
    wiki_url: str | None
    palette: list[str]
    silhouette: str | None
    note: str | None
    count: int
    first_seen: str | None
    last_seen: str | None
    # Field-guide enrichment (Phase 6); null until the background task runs.
    description: str | None = None
    family: str | None = None
    # eBird's species code ("blujay"), for the eBird and All About Birds links.
    # Null for a species outside the taxonomy.
    ebird_code: str | None = None
    # Local hours (0-23) with the most visits over the last 30 days, busiest
    # first, at most two. Null unless the request sent `tz`.
    peak_hours: list[int] | None = None


@dataclass
class HourStatsResponse:
    # Visits per local hour, index 0 is midnight to 1 am. Always 24 entries.
    counts: list[int]
    total: int
    # Distinct peaks, busiest first, at most two. Empty when there are no visits.
    peak_hours: list[int]
    # Local time of day, "HH:MM", of the earliest and latest visit in the window.
    earliest: str | None
    latest: str | None


@dataclass
class DashboardResponse:
    today_sightings: int
    species_this_week: int
    avg_confidence: float | None
    most_frequent: str | None
    most_frequent_count: int
    total_species: int
    total_devices: int
    spark_sightings: list[int]
    spark_species: list[int]
    spark_confidence: list[float]


@dataclass
class StorageResponse:
    # The whole database on disk, from pg_database_size().
    database_bytes: int
    # Full sighting images plus their thumbnails, summed over every row.
    image_bytes: int
    # Age in days past which "Unknown" sightings are deleted. 0 means the
    # retention rule is off. Set by RETENTION_UNKNOWN_DAYS.
    retention_unknown_days: int
