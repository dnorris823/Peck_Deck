from dataclasses import dataclass


@dataclass
class CreateSpecies:
    common_name: str
    genus: str
    species_name: str
    order_name: str | None = None
    wiki_url: str | None = None


@dataclass
class SpeciesResponse:
    id: int
    common_name: str
    genus: str
    species_name: str
    order_name: str | None
    wiki_url: str | None
