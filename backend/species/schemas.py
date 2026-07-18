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
