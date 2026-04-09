"""Tests for Phase 5: Debug integration."""
from core.debug import PipelineInspector
from core.engine import PipelineContext


class TestPipelineInspector:
    """Test PipelineInspector functionality."""

    def test_summary(self):
        ctx = PipelineContext(symbols=['AAPL', 'MSFT'], regime='bull_strong', status='completed')
        ctx.phase_times = {'phase1': 5.0, 'phase2': 3.0}
        inspector = PipelineInspector(ctx)
        summary = inspector.summary()
        assert 'completed' in summary
        assert 'bull_strong' in summary
        assert '2' in summary  # symbol count
        assert 'Total: 8.0s' in summary

    def test_summary_with_error(self):
        ctx = PipelineContext(status='failed', error_message='something broke')
        inspector = PipelineInspector(ctx)
        assert 'something broke' in inspector.summary()

    def test_phase_status(self):
        ctx = PipelineContext(status='completed')
        ctx.phase_times = {'phase1': 5.0, 'phase2': 3.0}
        inspector = PipelineInspector(ctx)
        status = inspector.phase_status()
        assert status['phase1'] == 'done (5.0s)'
        assert status['phase2'] == 'done (3.0s)'
        assert status['phase3'] == 'pending'  # completed but not in times

    def test_candidate_breakdown(self):
        ctx = PipelineContext()
        ctx.candidates = []
        ctx.top_30 = []
        ctx.top_10 = []
        inspector = PipelineInspector(ctx)
        breakdown = inspector.candidate_breakdown()
        assert breakdown['candidates'] == {}
        assert breakdown['top_30'] == {}

    def test_debug_phase_no_data(self):
        ctx = PipelineContext()
        inspector = PipelineInspector(ctx)
        assert 'No phase data' in inspector.debug_phase('phase1')
