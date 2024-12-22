
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
        self.device_user_ids = None
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
                                               data=json.dumps(update_user_request),
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
    
    async def create_device(self, name: str = 'test_device', city: str = 'spokompton', state: str = 'WA'):
        
        await self.login_user()
        await self.create_user()
        
        create_device_request = {'records_list': [{'name': name, 
                                                   'city': city, 
                                                   'state': state, 
                                                   'owner': self.user_ids[0]}]}

        response = await self.test_client.post("/devices/create", 
                                               data=json.dumps(create_device_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        self.device_ids = [device.get('device_id') for device in response_body.get('body')]
        self.device_user_ids = [device.get('device_user_id') for device in response_body.get('body')]
        return response
    
    async def update_device(self, name: str = 'test_device2', city: str = 'rain_city', state: str = 'cascadia'):
        
        await self.login_user()
        await self.create_user()
        await self.create_device()
        
        update_device_request = {'records_list': [{'device_id': self.device_ids[0], 
                                                 'name': name, 
                                                 'city': city, 
                                                 'state': state}]}

        response = await self.test_client.patch("/devices/update", 
                                               data=json.dumps(update_device_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_device(self):
        
        await self.login_user()
        await self.create_user()
        await self.create_device()
        
        delete_device_request = {'records_list': [{'device_id': self.device_ids[0]}]}

        response = await self.test_client.post("/devices/delete", 
                                               data=json.dumps(delete_device_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def device_add_user(self):
        
        await self.login_user()
        await self.create_user()
        await self.create_device()
        
        device_add_user_request = {'records_list': [{'device_id': self.device_ids[0], 'user_id': 1}]}

        response = await self.test_client.post("/devices/add_users", 
                                               data=json.dumps(device_add_user_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        for id in [device_user.get('device_user_id') for device_user in response_body.get('body')]:
            self.device_user_ids.append(id)
        
        return response
    
    async def remove_device_user(self):
        
        await self.login_user()
        await self.create_user()
        await self.create_device()
        await self.device_add_user()
        
        remove_device_user_request = {'records_list': [{'device_user_id': self.device_user_ids[1]}]}

        response = await self.test_client.post("/devices/remove_users", 
                                               data=json.dumps(remove_device_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response