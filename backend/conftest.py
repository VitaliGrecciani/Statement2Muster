import asyncio
import pytest
from app.db.session import init_db

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    asyncio.run(init_db())
