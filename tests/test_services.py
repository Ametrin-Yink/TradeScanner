"""Tests for ServiceRegistry and logging_config."""
import pytest
from core.services.registry import ServiceRegistry
from core.logging_config import setup_logging


class TestServiceRegistry:
    """Test service registry CRUD operations."""

    def setup_method(self):
        ServiceRegistry.reset()

    def teardown_method(self):
        ServiceRegistry.reset()

    def test_register_and_get(self):
        ServiceRegistry.register('test', lambda: 'hello')
        assert ServiceRegistry.get('test') == 'hello'

    def test_lazy_initialization(self):
        call_count = 0
        def factory():
            nonlocal call_count
            call_count += 1
            return 'created'

        ServiceRegistry.register('lazy', factory)
        assert call_count == 0  # not created yet
        ServiceRegistry.get('lazy')
        assert call_count == 1
        ServiceRegistry.get('lazy')
        assert call_count == 1  # singleton - not called again

    def test_override(self):
        ServiceRegistry.register('svc', lambda: 'original')
        ServiceRegistry.override('svc', 'mocked')
        assert ServiceRegistry.get('svc') == 'mocked'

    def test_reset(self):
        ServiceRegistry.register('svc', lambda: 'val')
        ServiceRegistry.get('svc')
        ServiceRegistry.reset()
        assert not ServiceRegistry.has('svc')

    def test_has(self):
        assert not ServiceRegistry.has('nonexistent')
        ServiceRegistry.register('x', lambda: 1)
        assert ServiceRegistry.has('x')

    def test_get_unregistered_raises(self):
        with pytest.raises(KeyError):
            ServiceRegistry.get('nonexistent')

    def test_override_unregistered(self):
        """Override on unregistered service should work."""
        ServiceRegistry.override('unreg', 'mocked')
        assert ServiceRegistry.get('unreg') == 'mocked'

    def test_reregister_after_override(self):
        """Re-register should replace overridden instance."""
        ServiceRegistry.override('svc', 'mocked')
        assert ServiceRegistry.get('svc') == 'mocked'
        ServiceRegistry.register('svc', lambda: 'real')
        assert ServiceRegistry.get('svc') == 'real'

    def test_register_defaults(self):
        """register_defaults should not crash and should register core services."""
        from core.services.providers import register_defaults
        register_defaults()
        assert ServiceRegistry.has('database')
        assert ServiceRegistry.has('fetcher')
        assert ServiceRegistry.has('settings')


class TestSetupLogging:
    """Test centralized logging configuration."""

    def test_setup_logging_no_error(self):
        """Should not raise on setup."""
        setup_logging()

    def test_setup_logging_with_filters(self):
        setup_logging(component_filters={'test.logger': 'DEBUG'})

    def test_setup_logging_verbose(self):
        setup_logging(verbose=True)

    def test_setup_logging_adds_handler(self):
        """Should add at least one handler to root logger."""
        import logging
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_component_filter_takes_effect(self):
        """Component filter should set the logger's level."""
        import logging
        setup_logging(component_filters={'my.component': 'DEBUG'})
        assert logging.getLogger('my.component').level == logging.DEBUG
