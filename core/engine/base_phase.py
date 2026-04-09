"""Base interface for pipeline phase handlers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .context import PipelineContext


@dataclass
class PhaseResult:
    """Standard result from a phase handler."""
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class PhaseHandler(ABC):
    """Base interface for all pipeline phases."""

    NAME: str = ""
    DESCRIPTION: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._enabled = True

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> PhaseResult:
        """Execute this phase, reading from and writing to ctx."""
        pass

    def can_skip(self, ctx: PipelineContext) -> bool:
        """Override to implement conditional skip logic."""
        return False

    def validate_preconditions(self, ctx: PipelineContext) -> bool:
        """Check if this phase's prerequisites are met."""
        return True
