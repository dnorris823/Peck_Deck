
from sqlalchemy.sql import select
from sqlalchemy.exc import NoResultFound

import pytest

from database.models import Sightings
from api.tests.fixture_helper import FixtureHelper

class TestSightingsEndpoints:
    
    @pytest.mark.asyncio
    async def test_create_sighting(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.create_sighting()
        response_body = response.json().get('body')[0]
        
    
        async with init_db() as session:
            sighting = await session.execute(select(Sightings).where(Sightings.id == fixture_helper.sighting_ids[0]))
            sighting = sighting.scalar_one()
            assert sighting.id == fixture_helper.sighting_ids[0]
            assert sighting.species_id == fixture_helper.species_ids[0]
            assert sighting.device_id == fixture_helper.device_ids[0]
            assert sighting.photo_storage_location == 'test_location'
            assert sighting.weather_conditions == 'raining'
            assert sighting.feed_type == 'seeds'
            
            assert response.json().get('code') == 201
            assert response_body.get('sighting_id') == fixture_helper.sighting_ids[0]
            assert response_body.get('species_id') == fixture_helper.species_ids[0]
            assert response_body.get('device_id') == fixture_helper.device_ids[0]
            assert response_body.get('photo_storage_location') == 'test_location'
            assert response_body.get('weather_conditions') == 'raining'
            assert response_body.get('feed_type') == 'seeds'
                    
    @pytest.mark.asyncio
    async def test_update_sighting(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.update_sighting()
        response_body = response.json().get('body')[0]
        
        async with init_db() as session:
            sighting = await session.execute(select(Sightings).where(Sightings.id == fixture_helper.sighting_ids[0]))
            sighting = sighting.scalar_one()
            assert sighting.photo_storage_location == 'test_location2'
            assert sighting.weather_conditions == 'sunny'
            assert sighting.feed_type == 'insects'
            
            assert response.json().get('code') == 200
            assert response_body.get('photo_storage_location') == 'test_location2'
            assert response_body.get('weather_conditions') == 'sunny'
            assert response_body.get('feed_type') == 'insects'
    
    @pytest.mark.asyncio
    async def test_delete_sighting(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.delete_sighting()
        
        async with init_db() as session:
            
            with pytest.raises(NoResultFound):
                sighting = await session.execute(select(Sightings).where(Sightings.id == fixture_helper.sighting_ids[0]))
                sighting = sighting.scalar_one()
                
            assert response.status_code == 204