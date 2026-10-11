"""Fixtures pytest : base de test isolee, recreee avant chaque test."""
import os
import pathlib

import psycopg2
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DB_HOST", os.environ.get("DB_HOST", "localhost"))
os.environ.setdefault("DB_PORT", os.environ.get("DB_PORT", "5432"))
os.environ.setdefault("DB_NAME", "terrain_foot_test")
os.environ.setdefault("DB_USER", os.environ.get("DB_USER", "postgres"))
os.environ.setdefault("DB_PASSWORD", os.environ.get("DB_PASSWORD", "postgres"))

SCHEMA_SQL = (pathlib.Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()
SEED_SQL = (pathlib.Path(__file__).resolve().parent.parent / "db" / "seed.sql").read_text()

TABLES = [
    "reservation_equipement",
    "reservation",
    "terrain_service",
    "equipement",
    "terrain",
    "service",
    "type_terrain",
    "client",
]


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    """Cree le schema une fois pour toute la session de tests."""
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.close()
    yield


@pytest.fixture(autouse=True)
def _clean_database():
    """Vide toutes les tables et recharge les donnees de demo avant chaque test."""
    from app.database import reset_pool

    reset_pool()
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        cur.execute(SEED_SQL)
    conn.close()
    yield
    reset_pool()


@pytest.fixture()
def client():
    from app.main import app

    return TestClient(app)
