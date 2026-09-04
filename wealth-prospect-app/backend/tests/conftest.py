import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SEED_COUNT"] = "30"
os.environ["LIVE_CONNECTORS"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
