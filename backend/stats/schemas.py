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
