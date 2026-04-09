"""Shared state carrier between pipeline phases."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PipelineContext:
    """Carries state between pipeline phases.

    Each phase reads from and writes to this context.
    """
    symbols: List[str] = field(default_factory=list)
    regime: Optional[str] = None
    regime_analysis: Dict[str, Any] = field(default_factory=dict)
    candidates: List = field(default_factory=list)
    top_30: List = field(default_factory=list)
    top_10: List = field(default_factory=list)
    report_path: Optional[str] = None
    phase_times: Dict[str, float] = field(default_factory=dict)
    run_date: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    fail_symbols: List[str] = field(default_factory=list)

    # Raw phase results for passing between handlers
    _phase_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def set_phase_data(self, phase: str, data: Dict[str, Any]) -> None:
        self._phase_data[phase] = data
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def get_phase_data(self, phase: str) -> Dict[str, Any]:
        return self._phase_data.get(phase, {})
