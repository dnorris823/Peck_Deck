
import json

from litestar.testing import AsyncTestClient

from sqlalchemy.ext.asyncio import async_sessionmaker

class FixtureHelper:
    
    def __init__(self, test_client: AsyncTestClient, async_session: async_sessionmaker):
        self.test_client = test_client
        self.async_session = async_session
        self.jwt_token = None
        self.user_ids = None
        self.device_ids = None
        self.species_ids = None
        self.sighting_ids = None
        
    async def login_user(self, email: str = 'test@peckdeck.com', password: str = 'test123'):
        
        login_request = {'email': email, 'password': password}
        
        response = await self.test_client.post("/login", json=login_request)
        
        self.jwt_token = response.headers.get("Authorization")
        return response
        
    async def create_user(self, email: str = 'test2@peckdeck.com', password: str = 'test123'):
        
        await self.login_user()
        
        create_user_request = {'records_list': [{'email': email, 'password': password}]}

        response = await self.test_client.post("/users/create", 
                                               data=json.dumps(create_user_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        self.user_ids = [user.get('user_id') for user in response_body.get('body')]
        return response
    
    async def update_user(self, email: str = 'test3@peckdeck.com'):
        
        await self.login_user()
        await self.create_user()
        
        update_user_request = {'records_list': [{'user_id': self.user_ids[0], 'email': email}]}

        response = await self.test_client.patch("/users/update", 
                                               json=json.dumps(update_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_user(self):
        
        await self.login_user()
        await self.create_user()
        
        delete_user_request = {'records_list': [{'user_id': self.user_ids[0]}]}

        response = await self.test_client.post("/users/delete", 
                                               data=json.dumps(delete_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response