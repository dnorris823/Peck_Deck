
import os

import uvicorn

from litestar import Litestar, Router
from litestar.openapi import OpenAPIConfig

from api.devices.device_controller import DeviceController
from api.species.species_controller import SpeciesController
from api.users.user_controller import UsersController
from api.sightings.sighting_controller import SightingsController

from api.jwt_middleware import login_handler, jwt_auth
from api.load_model import cv_model

user_router = Router(path='/users', route_handlers=[UsersController])
device_router = Router(path='/devices', route_handlers=[DeviceController])
species_router = Router(path="/species", route_handlers=[SpeciesController])
sighting_router = Router(path="/sightings", route_handlers=[SightingsController])

app = Litestar(route_handlers=
               [login_handler,
                species_router, 
                device_router,
                user_router,
                sighting_router],
               openapi_config=OpenAPIConfig(title="Peck_Deck API", version="1.0.0"),
               on_app_init=[jwt_auth.on_app_init],
               on_startup=[cv_model],  # Runs once for the entire app
               debug=True,
               pdb_on_exception=True)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
