
from sqlalchemy.sql import select

import pytest

from database.models import Users
from api.tests.fixture_helper import FixtureHelper

class TestBasicEndpoints:
    
    @pytest.mark.asyncio
    async def test_database_init(self, init_db):
        async with init_db() as session:
            async with session.begin():
                user = await session.execute(select(Users).where(Users.email == 'test@peckdeck.com'))
                user = user.scalar_one()
                assert user.email == 'test@peckdeck.com'
                assert user.password != 'test123'
                
    @pytest.mark.asyncio
    async def test_login(self, init_db, test_client):
        
        fixture_helper = FixtureHelper(test_client, init_db)
        response = await fixture_helper.login_user('test@peckdeck.com', 'test123')
        print(f"TOKEN: {fixture_helper.jwt_token}")
        
        assert response.status_code == 201
        assert response.headers.get("Authorization") is not None