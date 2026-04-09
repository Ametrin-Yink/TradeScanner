"""Pipeline orchestrator that chains PhaseHandlers."""
import logging
import time
from typing import Dict, Any, List, Tuple, Optional

from .context import PipelineContext
from .base_phase import PhaseHandler, PhaseResult

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Chains PhaseHandlers into an executable pipeline."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.handlers: List[Tuple[str, PhaseHandler]] = []
        self._load_default_handlers()

    def _load_default_handlers(self):
        from .phase_handlers import (
            Phase0PrepHandler, Phase1RegimeHandler,
            Phase2ScreeningHandler, Phase3AIScoringHandler,
            Phase4DeepAnalysisHandler, Phase5ReportHandler,
            Phase6NotifyHandler,
        )
        self.handlers = [
            ("phase0", Phase0PrepHandler(self.config.get("phase0"))),
            ("phase1", Phase1RegimeHandler(self.config.get("phase1"))),
            ("phase2", Phase2ScreeningHandler(self.config.get("phase2"))),
            ("phase3", Phase3AIScoringHandler(self.config.get("phase3"))),
            ("phase4", Phase4DeepAnalysisHandler(self.config.get("phase4"))),
            ("phase5", Phase5ReportHandler(self.config.get("phase5"))),
            ("phase6", Phase6NotifyHandler(self.config.get("phase6"))),
        ]

    def add_handler(self, name: str, handler: PhaseHandler) -> None:
        self.handlers.append((name, handler))

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Execute all enabled phases in order."""
        for name, handler in self.handlers:
            if not handler._enabled:
                logger.info(f"Skipping {name} (disabled)")
                continue
            if handler.can_skip(ctx):
                logger.info(f"Skipping {name} (precondition not met)")
                continue
            if not handler.validate_preconditions(ctx):
                ctx.status = "failed"
                ctx.error_message = f"Preconditions failed for {name}"
                return ctx

            phase_start = time.time()
            try:
                result = handler.execute(ctx)
            except Exception as e:
                logger.exception(f"Phase {name} failed: {e}")
                ctx.status = "failed"
                ctx.error_message = str(e)
                return ctx

            ctx.phase_times[name] = time.time() - phase_start

            if not result.success:
                ctx.status = "failed"
                ctx.error_message = result.error
                return ctx

            # Merge phase data into context
            for key, value in result.data.items():
                if hasattr(ctx, key):
                    setattr(ctx, key, value)
                ctx._phase_data[key] = value

        if ctx.status != "failed":
            ctx.status = "completed"

        return ctx
