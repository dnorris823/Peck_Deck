
from sqlalchemy.sql import select
from sqlalchemy.exc import NoResultFound

import pytest

from database.models import Users
from api.tests.fixture_helper import FixtureHelper

class TestUserEndpoints:
    
    @pytest.mark.asyncio
    async def test_create_user(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.create_user('test2@peckdeck.com', 'test123')
        response_body = response.json().get('body')[0]
        
    
        async with init_db() as session:
            user = await session.execute(select(Users).where(Users.id == fixture_helper.user_ids[0]))
            user = user.scalar_one()
            assert user.email == 'test2@peckdeck.com'
            assert user.password != 'test123'
            
            assert response.json().get('code') == 201
            assert response_body.get('email') == 'test2@peckdeck.com'
            assert response_body.get('user_id') == fixture_helper.user_ids[0]
                    
    @pytest.mark.asyncio
    async def test_update_user(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.update_user()
        response_body = response.json().get('body')[0]
        
        async with init_db() as session:
            user = await session.execute(select(Users).where(Users.id == fixture_helper.user_ids[0]))
            user = user.scalar_one()
            assert user.email == 'test3@peckdeck.com'
            
            assert response.json().get('code') == 200
            assert response_body.get('email') == 'test3@peckdeck.com'
            assert response_body.get('user_id') == fixture_helper.user_ids[0]
    
    @pytest.mark.asyncio
    async def test_delete_user(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.delete_user()
        
        async with init_db() as session:
            
            with pytest.raises(NoResultFound):
                user = await session.execute(select(Users).where(Users.id == fixture_helper.user_ids[0]))
                user = user.scalar_one()
                
            assert response.status_code == 204