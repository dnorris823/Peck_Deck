
import os
from typing import Any

from pydantic import BaseModel, EmailStr

from litestar import Response, post
from litestar.connection import ASGIConnection
from litestar.di import Provide
from litestar.security.jwt import Token
from litestar.security.jwt import JWTAuth

from passlib.context import CryptContext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db
from database.models import Users

# Let's assume we have a User model that is a pydantic model.
# This though is not required - we need some sort of user class -
# but it can be any arbitrary value, e.g. an SQLAlchemy model, a representation of a MongoDB  etc.
class UserLogin(BaseModel):
    email: EmailStr
    password: str
    
class UserLoginResponse(BaseModel):
    user_id: int
    email: str
    
# JWTAuth requires a retrieve handler callable that receives the JWT token model and the ASGI connection
# and returns the 'User' instance correlating to it.
async def retrieve_user_handler(token: Token, connection: "ASGIConnection[Any, Any, Any, Any]") -> int | None:
    return token.sub

print(f"JWT SECRET: {os.getenv('JWT_SECRET')}")
jwt_auth = JWTAuth[UserLogin](
    retrieve_user_handler=retrieve_user_handler,
    token_secret=os.getenv("JWT_SECRET", "test_secret"),
    exclude=["/login", "/schema"],
)

# Given an instance of 'JWTAuth' we can create a login handler function:
@post("/login", dependencies={'db_connection': Provide(connect_to_db)})
async def login_handler(data: UserLogin, db_connection: async_sessionmaker) -> Response[UserLoginResponse]:
    
    # Initialize Passlib CryptContext with Argon2
    pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
    
    # logic here to retrieve the user instance
    req_data = data
    req_data = req_data.model_dump()
    print(f"REQ_DATA: {req_data.get('email')}")

    async with db_connection() as session:
        
        
        user = await session.execute(select(Users).where(Users.email == req_data.get('email')))
        user = user.scalar_one()
        
        # Verify the password
        if pwd_context.verify(req_data.get('password'), user.password):
            user_login_response = UserLoginResponse(**{'user_id': user.id, 'email': user.email})
            return jwt_auth.login(identifier=str(user.id), 
                                token_extras={"email": user.email}, 
                                response_body=user_login_response)
