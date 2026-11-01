from dataclasses import dataclass, field


@dataclass
class CreateSpecies:
    common_name: str
    genus: str
    species_name: str
    order_name: str | None = None
    wiki_url: str | None = None
    palette: list[str] | None = None
    silhouette: str | None = None
    note: str | None = None


@dataclass
class SpeciesResponse:
    id: int
    common_name: str
    genus: str
    species_name: str
    order_name: str | None
    wiki_url: str | None
    palette: list[str]
    silhouette: str | None
    note: str | None
    # Field-guide enrichment (Phase 6); null until the background task runs.
    description: str | None = None
    family: str | None = None
    # eBird's species code ("blujay"), for the eBird and All About Birds links.
    # Null for a species outside the taxonomy.
    ebird_code: str | None = None
    # "bird", or "animal" for a feeder mammal Tier 2 named.
    kind: str = "bird"
    # The animal's group, such as "squirrel". Null for a bird.
    animal_group: str | None = None
