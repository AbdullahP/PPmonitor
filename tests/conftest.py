"""Shared test fixtures."""

import asyncio
import os
import socket
import threading
import time

import pytest
import pytest_asyncio
import uvicorn

from mock_server.server import app as mock_app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def mock_server_url():
    """Start mock bol.com server and return its base URL."""
    port = _find_free_port()
    config = uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def state():
    """StateManager connected to test PostgreSQL. Cleans tables between tests."""
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://pokemon:pokemon@localhost:5432/pokemon_monitor",
    )
    from monitor.state import StateManager

    mgr = await StateManager.create(db_url)

    async with mgr._pool.acquire() as conn:
        await conn.execute("DELETE FROM poll_log")
        await conn.execute("DELETE FROM alerts_sent")
        await conn.execute("DELETE FROM discovered_products")
        await conn.execute("DELETE FROM system_heartbeat")
        await conn.execute("DELETE FROM products")

    yield mgr
    await mgr.close()
