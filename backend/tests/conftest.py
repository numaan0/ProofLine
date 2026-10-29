import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.persistence import Base

# Device id the API test clients present; rows seeded for API tests belong to it.
TEST_DEVICE = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point every module that opens sessions at a throwaway SQLite file."""
    import app.models.inspection_models  # noqa: F401  (register tables)
    import app.api.inspections as api_mod
    import app.api.notifications as notif_mod
    import app.services.agent.orchestrator as orch_mod

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    monkeypatch.setattr(orch_mod, "async_session", session_factory)
    monkeypatch.setattr(api_mod, "async_session", session_factory)
    monkeypatch.setattr(notif_mod, "async_session", session_factory)
    yield session_factory
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def no_network_tool_loop(monkeypatch):
    """Tests never reach the live API: by default the investigation loop ends without tool calls."""
    from app.services.meta_client import meta_client

    async def no_tools(messages, tools=None, max_tokens=0, model=""):
        return {"role": "assistant", "content": "No further checks."}

    monkeypatch.setattr(meta_client, "chat", no_tools)
