

from typing import Optional
from pydantic import BaseModel


class SpeciesCreatorStruct(BaseModel):
    common_name: str
    genus: str
    species: str
    order: str
    wiki_url: str

class SpeciesUpdaterStruct(BaseModel):
    species_id: int
    common_name: str
    genus: str
    species: str
    order: str
    wiki_url: str

class SpeciesDeleterStruct(BaseModel):
    species_id: int

class SpeciesCreatorRequestSchema(BaseModel):

    records_list: list[SpeciesCreatorStruct]

class SpeciesUpdaterRequestSchema(BaseModel):

    records_list: list[SpeciesUpdaterStruct]

class SpeciesDeleterRequestSchema(BaseModel):

    records_list: list[SpeciesDeleterStruct]

class SpeciesResponseStruct(BaseModel):
    species_id: int
    common_name: str
    genus: str
    species: str
    order: str
    wiki_url: str

class SpeciesResponseSchema(BaseModel):
    code: int
    message: str
    body: list[SpeciesResponseStruct]