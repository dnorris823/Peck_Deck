
from litestar import Litestar, Router
from litestar.openapi import OpenAPIConfig

from api.devices.device_controller import DeviceController
from api.species.species_controller import SpeciesController
from api.users.user_controller import UsersController

user_router = Router(path='/users', route_handlers=[UsersController])
device_router = Router(path='/devices', route_handlers=[DeviceController])
species_router = Router(path="/species", route_handlers=[SpeciesController])


app = Litestar(route_handlers=[species_router, 
                               user_router],
               openapi_config=OpenAPIConfig(title="Peck_Deck API", version="1.0.0"))
