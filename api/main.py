
import os

from litestar import Litestar, Router
from litestar.openapi import OpenAPIConfig
from litestar.security.jwt import JWTAuth

from api.devices.device_controller import DeviceController
from api.species.species_controller import SpeciesController
from api.users.user_controller import UsersController

from api.jwt_middleware import login_handler, UserLogin, retrieve_user_handler

user_router = Router(path='/users', route_handlers=[UsersController])
device_router = Router(path='/devices', route_handlers=[DeviceController])
species_router = Router(path="/species", route_handlers=[SpeciesController])


jwt_auth = JWTAuth[UserLogin](
    retrieve_user_handler=retrieve_user_handler,
    token_secret=os.getenv.get("JWT_SECRET"),
    exclude=["/login", "/schema"],
)

app = Litestar(route_handlers=[login_handler,
                               species_router, 
                               user_router],
               openapi_config=OpenAPIConfig(title="Peck_Deck API", version="1.0.0"),
               on_app_init=[jwt_auth.on_app_init])
