
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
        
        update_user_request = {'records_list': [{'user_id': self.user_ids[0], 'email': email}]}

        response = await self.test_client.patch("/users/update", 
                                               data=json.dumps(update_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_user(self):
        
        delete_user_request = {'records_list': [{'user_id': self.user_ids[0]}]}

        response = await self.test_client.post("/users/delete", 
                                               data=json.dumps(delete_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def create_device(self, name: str = 'test_device', city: str = 'spokompton', state: str = 'WA'):
        
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
        
        update_device_request = {'records_list': [{'device_id': self.device_ids[0], 
                                                 'name': name, 
                                                 'city': city, 
                                                 'state': state}]}

        response = await self.test_client.patch("/devices/update", 
                                               data=json.dumps(update_device_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_device(self):
        
        delete_device_request = {'records_list': [{'device_id': self.device_ids[0]}]}

        response = await self.test_client.post("/devices/delete", 
                                               data=json.dumps(delete_device_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def device_add_user(self):
        
        device_add_user_request = {'records_list': [{'device_id': self.device_ids[0], 'user_id': 1}]}

        response = await self.test_client.post("/devices/add_users", 
                                               data=json.dumps(device_add_user_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        for id in [device_user.get('device_user_id') for device_user in response_body.get('body')]:
            self.device_user_ids.append(id)
        
        return response
    
    async def remove_device_user(self):
        
        remove_device_user_request = {'records_list': [{'device_user_id': self.device_user_ids[1]}]}

        response = await self.test_client.post("/devices/remove_users", 
                                               data=json.dumps(remove_device_user_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def create_species(self, 
                             common_name: str = 'test_species', 
                             genus: str = 'gandalfius', 
                             species: str = 'fernius', 
                             order: str = 'test_order', 
                             wiki_url: str = 'https://en.wikipedia.org/wiki/test_species'):
        
        create_species_request = {'records_list': [{'common_name': common_name,
                                                    'genus': genus,
                                                   'species': species,
                                                   'order': order,
                                                   'wiki_url': wiki_url}]}

        response = await self.test_client.post("/species/create", 
                                               data=json.dumps(create_species_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        self.species_ids = [species.get('species_id') for species in response_body.get('body')]
        return response
    
    async def update_species(self, 
                             common_name: str = 'test_species2', 
                             genus: str = 'gandalfius2', 
                             species: str = 'fernius2'):
        
        update_species_request = {'records_list': [{'species_id': self.species_ids[0],
                                                    'common_name': common_name,
                                                    'genus': genus,
                                                    'species': species}]}

        response = await self.test_client.patch("/species/update", 
                                               data=json.dumps(update_species_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_species(self):
        
        delete_species_request = {'records_list': [{'species_id': self.species_ids[0]}]}

        response = await self.test_client.post("/species/delete", 
                                               data=json.dumps(delete_species_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def create_sighting(self):
        
        create_sighting_request = {'records_list': [{'species_id': self.species_ids[0], 
                                                   'device_id': self.device_ids[0], 
                                                   'photo_storage_location': 'test_location', 
                                                   'weather_conditions': 'raining',
                                                   'feed_type': 'seeds'}]}

        response = await self.test_client.post("/sightings/create", 
                                               data=json.dumps(create_sighting_request),
                                               headers={"Authorization": self.jwt_token})
        response_body = response.json()
        
        self.sighting_ids = [sighting.get('sighting_id') for sighting in response_body.get('body')]
        return response
    
    async def update_sighting(self, name: str = 'test_device2', city: str = 'rain_city', state: str = 'cascadia'):
        
        update_sighting_request = {'records_list': [{'sighting_id': self.sighting_ids[0],
                                                   'photo_storage_location': 'test_location2', 
                                                   'weather_conditions': 'sunny',
                                                   'feed_type': 'insects'}]}

        response = await self.test_client.patch("/sightings/update", 
                                               data=json.dumps(update_sighting_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response
    
    async def delete_sighting(self):
        
        delete_sighting_request = {'records_list': [{'sighting_id': self.sighting_ids[0]}]}

        response = await self.test_client.post("/sightings/delete", 
                                               data=json.dumps(delete_sighting_request),
                                               headers={"Authorization": self.jwt_token})
        
        return response