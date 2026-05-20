from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=False)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
