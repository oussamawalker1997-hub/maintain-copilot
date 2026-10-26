import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maintain.app import create_app
from maintain.cli import seed
from maintain.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/synthetic"


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / "maintain.sqlite"
    seed(database, FIXTURES)
    keys = json.loads((tmp_path / "demo-credentials.json").read_text(encoding="utf-8"))
    with TestClient(create_app(Settings(database, requests_per_minute=1000))) as client:
        yield client, database, keys


def headers(keys, user="tech-a"):
    return {"Authorization": "Bearer " + keys[user]}


def question(client, keys, text="E042", asset="NW-P17"):
    return client.post(
        "/v1/answers",
        headers=headers(keys),
        json={
            "asset_id": asset,
            "question": text,
        },
    )
