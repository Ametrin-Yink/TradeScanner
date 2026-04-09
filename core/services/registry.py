"""Service registry for dependency injection."""
from typing import Callable, Dict, Any, Optional


class ServiceRegistry:
    """Centralized service container with lazy initialization.

    Usage:
        ServiceRegistry.register('database', lambda: Database())
        db = ServiceRegistry.get('database')  # lazy singleton
        ServiceRegistry.override('database', mock_db)  # for testing
    """

    _factories: Dict[str, Callable] = {}
    _instances: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, factory: Callable) -> None:
        """Register a service factory (not an instance)."""
        cls._factories[name] = factory
        cls._instances.pop(name, None)  # invalidate cached instance

    @classmethod
    def get(cls, name: str) -> Any:
        """Get service instance, creating on first access (lazy singleton)."""
        if name not in cls._instances:
            if name not in cls._factories:
                raise KeyError(f"Service '{name}' not registered")
            cls._instances[name] = cls._factories[name]()
        return cls._instances[name]

    @classmethod
    def override(cls, name: str, instance: Any) -> None:
        """Override a service with a pre-built instance (for testing/mocking)."""
        cls._instances[name] = instance

    @classmethod
    def reset(cls) -> None:
        """Clear all registered services and instances."""
        cls._factories.clear()
        cls._instances.clear()

    @classmethod
    def has(cls, name: str) -> bool:
        """Check if a service is registered."""
        return name in cls._factories or name in cls._instances
