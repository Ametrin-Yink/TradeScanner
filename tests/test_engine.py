"""Tests for Phase 3-4: Pipeline Engine."""
import pytest
from core.engine import PipelineContext, PhaseHandler, PhaseResult, PipelineOrchestrator


class TestPipelineContext:
    """Test PipelineContext data carrier."""

    def test_default_values(self):
        ctx = PipelineContext()
        assert ctx.symbols == []
        assert ctx.status == "pending"
        assert ctx.regime is None
        assert ctx.error_message is None

    def test_set_and_get(self):
        ctx = PipelineContext()
        ctx.set('regime', 'bull_strong')
        assert ctx.regime == 'bull_strong'

    def test_phase_data(self):
        ctx = PipelineContext()
        ctx.set_phase_data('phase1', {'regime': 'bull', 'allocation': {}})
        assert ctx.regime == 'bull'
        assert ctx.get_phase_data('phase1') == {'regime': 'bull', 'allocation': {}}


class TestPhaseHandler:
    """Test PhaseHandler ABC."""

    def test_concrete_handler(self):
        class DummyHandler(PhaseHandler):
            NAME = "dummy"
            def execute(self, ctx):
                return PhaseResult(success=True, data={'result': 42})

        h = DummyHandler()
        ctx = PipelineContext()
        result = h.execute(ctx)
        assert result.success
        assert result.data['result'] == 42

    def test_can_skip_default(self):
        class DummyHandler(PhaseHandler):
            NAME = "dummy"
            def execute(self, ctx):
                return PhaseResult(success=True)

        h = DummyHandler()
        assert h.can_skip(PipelineContext()) is False

    def test_validate_preconditions_default(self):
        class DummyHandler(PhaseHandler):
            NAME = "dummy"
            def execute(self, ctx):
                return PhaseResult(success=True)

        h = DummyHandler()
        assert h.validate_preconditions(PipelineContext()) is True


class TestPipelineOrchestrator:
    """Test PipelineOrchestrator."""

    def test_run_single_phase(self):
        class DummyHandler(PhaseHandler):
            NAME = "dummy"
            def execute(self, ctx):
                return PhaseResult(success=True, data={'regime': 'bull'})

        pipeline = PipelineOrchestrator()
        pipeline.handlers = [("dummy", DummyHandler())]
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        assert result.status == "completed"
        assert result.regime == 'bull'

    def test_run_phase_failure_stops_pipeline(self):
        class FailHandler(PhaseHandler):
            NAME = "fail"
            def execute(self, ctx):
                return PhaseResult(success=False, error="boom")

        class NeverReached(PhaseHandler):
            NAME = "never"
            def execute(self, ctx):
                ctx.set('reached', True)
                return PhaseResult(success=True)

        pipeline = PipelineOrchestrator()
        pipeline.handlers = [("fail", FailHandler()), ("never", NeverReached())]
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        assert result.status == "failed"
        assert result.error_message == "boom"
        assert not hasattr(ctx, 'reached') or ctx.reached is not True

    def test_run_exception_stops_pipeline(self):
        class BoomHandler(PhaseHandler):
            NAME = "boom"
            def execute(self, ctx):
                raise RuntimeError("unexpected error")

        pipeline = PipelineOrchestrator()
        pipeline.handlers = [("boom", BoomHandler())]
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        assert result.status == "failed"
        assert "unexpected error" in result.error_message
