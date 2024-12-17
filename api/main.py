
from litestar import Litestar, Router
from litestar.openapi import OpenAPIConfig

from api.species.species_controller import SpeciesController
species_router = Router(path="/species", route_handlers=[SpeciesController])


app = Litestar(route_handlers=[species_router],
               openapi_config=OpenAPIConfig(title="Peck_Deck API", version="1.0.0"))
