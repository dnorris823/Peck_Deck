
from sqlalchemy.sql import select
from sqlalchemy.exc import NoResultFound

import pytest

from database.models import Devices, DeviceUsers
from api.tests.fixture_helper import FixtureHelper

class TestDeviceEndpoints:
    
    @pytest.mark.asyncio
    async def test_create_device(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        await fixture_helper.login_user()
        await fixture_helper.create_user()
        response = await fixture_helper.create_device()
        response_body = response.json().get('body')[0]
        
    
        async with init_db() as session:
            device = await session.execute(select(Devices).where(Devices.id == fixture_helper.device_ids[0]))
            device = device.scalar_one()
            assert device.name == 'test_device'
            assert device.city == 'spokompton'
            assert device.state == 'WA'
            assert device.owner == fixture_helper.user_ids[0]
            
            assert response.json().get('code') == 201
            assert response_body.get('name') == 'test_device'
            assert response_body.get('city') == 'spokompton'
            assert response_body.get('state') == 'WA'
            assert response_body.get('owner') == fixture_helper.user_ids[0]
            assert response_body.get('device_user_id') == fixture_helper.device_user_ids[0]
                    
    @pytest.mark.asyncio
    async def test_update_device(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        await fixture_helper.login_user()
        await fixture_helper.create_user()
        await fixture_helper.create_device()
        response = await fixture_helper.update_device()
        response_body = response.json().get('body')[0]
        
        async with init_db() as session:
            device = await session.execute(select(Devices).where(Devices.id == fixture_helper.device_ids[0]))
            device = device.scalar_one()
            assert device.name == 'test_device2'
            assert device.city == 'rain_city'
            assert device.state == 'cascadia'
            assert device.owner == fixture_helper.user_ids[0]
            
            assert response.json().get('code') == 200
            assert response_body.get('name') == 'test_device2'
            assert response_body.get('city') == 'rain_city'
            assert response_body.get('state') == 'cascadia'
            assert response_body.get('owner') == fixture_helper.user_ids[0]
    
    @pytest.mark.asyncio
    async def test_delete_device(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        await fixture_helper.login_user()
        await fixture_helper.create_user()
        await fixture_helper.create_device()
        response = await fixture_helper.delete_device()
        
        async with init_db() as session:
            
            with pytest.raises(NoResultFound):
                device = await session.execute(select(Devices).where(Devices.id == fixture_helper.device_ids[0]))
                device = device.scalar_one()
                
            assert response.status_code == 204
            
    @pytest.mark.asyncio
    async def test_device_add_user(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        await fixture_helper.login_user()
        await fixture_helper.create_user()
        await fixture_helper.create_device()
        response = await fixture_helper.device_add_user()
        response_body = response.json().get('body')[0]
        
        async with init_db() as session:
            device_user = await session.execute(select(DeviceUsers).where(DeviceUsers.device_id == fixture_helper.device_ids[0]))
            device_user = device_user.scalars().all()
            assert device_user[0].id == fixture_helper.device_user_ids[0]
            assert device_user[0].device_id == fixture_helper.device_ids[0]
            assert device_user[0].user_id == fixture_helper.user_ids[0]
            
            assert response.json().get('code') == 201
            assert response_body.get('device_user_id') == fixture_helper.device_user_ids[1]
            assert response_body.get('device_id') == fixture_helper.device_ids[0]
            assert response_body.get('user_id') == 1
            
    @pytest.mark.asyncio
    async def test_delete_device_user(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        await fixture_helper.login_user()
        await fixture_helper.create_user()
        await fixture_helper.create_device()
        await fixture_helper.device_add_user()
        response = await fixture_helper.remove_device_user()
        
        async with init_db() as session:
            
            with pytest.raises(NoResultFound):
                device = await session.execute(select(DeviceUsers).where(DeviceUsers.id == fixture_helper.device_user_ids[1]))
                device = device.scalar_one()
                
            assert response.status_code == 204
    