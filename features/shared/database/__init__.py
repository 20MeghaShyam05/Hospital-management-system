# =============================================================================
# database/__init__.py
# Database layer package — exports the three store classes and the
# get_store() factory that the rest of the app uses.
# =============================================================================
# Architecture
# ------------
# InMemoryStore   — always available, zero deps, data lost on restart (F2)
# PostgresManager — primary persistent store; falls back to InMemory on failure
# MongoManager    — audit / log store only; falls back to InMemory on failure
#
# Every other layer (services, adapters, API) imports from here:
#
#   from database import get_store, get_mongo, InMemoryStore
# =============================================================================

from features.shared.database.in_memory import InMemoryStore
from features.shared.database.postgres  import PostgresManager
from features.shared.database.mongo     import MongoManager


def get_store(config: dict | None = None) -> PostgresManager:
    """Return a PostgresManager (which falls back to InMemory if PG is down).

    Parameters
    ----------
    config : optional dict with keys: host, port, dbname, user, password
             If None, values are read from config.py settings.
    """
    return PostgresManager(config=config)


def get_mongo(config: dict | None = None) -> MongoManager:
    """Return a MongoManager (which falls back to InMemory audit log if Mongo is down)."""
    return MongoManager(config=config)


__all__ = [
    "InMemoryStore",
    "PostgresManager",
    "MongoManager",
    "get_store",
    "get_mongo",
]
