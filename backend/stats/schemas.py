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
class NewSpeciesResponse:
    id: int
    common_name: str
    first_seen: str


@dataclass
class DeviceCountResponse:
    device_id: int
    count: int


@dataclass
class InsightsResponse:
    """Analytics over a selectable window — see stats.operations.insights."""

    days: int
    device_id: int | None
    total_sightings: int
    distinct_species: int
    day_labels: list[str]
    per_day: list[int]
    diversity: list[int]
    hours: list[int]
    busiest_hour: int | None
    busiest_day: str | None
    active_days: int
    longest_streak: int
    new_species: list[NewSpeciesResponse]
    per_device: list[DeviceCountResponse]


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
