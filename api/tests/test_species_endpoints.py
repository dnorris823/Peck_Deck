from sqlalchemy.sql import select
from sqlalchemy.exc import NoResultFound

import pytest

from database.models import Species
from api.tests.fixture_helper import FixtureHelper

class TestSpeciesEndpoints:
    
    @pytest.mark.asyncio
    async def test_create_species(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.create_species()
        response_body = response.json().get('body')[0]
        
    
        async with init_db() as session:
            species = await session.execute(select(Species).where(Species.id == fixture_helper.species_ids[0]))
            species = species.scalar_one()
            assert species.common_name == 'test_species'
            assert species.genus == 'gandalfius'
            assert species.species == 'fernius'
            assert species.order == 'test_order'
            assert species.wiki_url == 'https://en.wikipedia.org/wiki/test_species'
            
            assert response.json().get('code') == 201
            assert response_body.get('common_name') == 'test_species'
            assert response_body.get('genus') == 'gandalfius'
            assert response_body.get('species') == 'fernius'
            assert response_body.get('order') == 'test_order'
            assert response_body.get('wiki_url') == 'https://en.wikipedia.org/wiki/test_species'
                    
    @pytest.mark.asyncio
    async def test_update_species(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.update_species()
        response_body = response.json().get('body')[0]
        
        async with init_db() as session:
            species = await session.execute(select(Species).where(Species.id == fixture_helper.species_ids[0]))
            species = species.scalar_one()
            assert species.common_name == 'test_species2'
            assert species.genus == 'gandalfius2'
            assert species.species == 'fernius2'
            
            assert response.json().get('code') == 200
            assert response_body.get('common_name') == 'test_species2'
            assert response_body.get('genus') == 'gandalfius2'
            assert response_body.get('species') == 'fernius2'
    
    @pytest.mark.asyncio
    async def test_delete_species(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.delete_species()
        
        async with init_db() as session:
            
            with pytest.raises(NoResultFound):
                species = await session.execute(select(Species).where(Species.id == fixture_helper.species_ids[0]))
                species = species.scalar_one()
                
            assert response.status_code == 204