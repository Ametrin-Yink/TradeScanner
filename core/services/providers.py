"""Factory functions for core services."""
from config.settings import settings
from data.db import Database
from core.fetcher import DataFetcher


def create_database() -> Database:
    """Create Database instance."""
    return Database()


def create_fetcher() -> DataFetcher:
    """Create DataFetcher instance, injecting Database from registry."""
    from core.services import ServiceRegistry
    return DataFetcher(db=ServiceRegistry.get('database'))


def create_settings():
    """Return the global settings singleton."""
    return settings


def register_defaults():
    """Register all default service factories.

    Call this once at application startup.
    """
    from core.services import ServiceRegistry
    if not ServiceRegistry.has('database'):
        ServiceRegistry.register('database', create_database)
    if not ServiceRegistry.has('fetcher'):
        ServiceRegistry.register('fetcher', create_fetcher)
    if not ServiceRegistry.has('settings'):
        ServiceRegistry.register('settings', create_settings)
