"""Runtime inspection of pipeline state."""
from typing import Dict, List, Any, Optional


class PipelineInspector:
    """Runtime inspection of pipeline state."""

    def __init__(self, ctx):
        self.ctx = ctx

    def summary(self) -> str:
        """Print pipeline state summary."""
        lines = [
            f"Status: {self.ctx.status}",
            f"Run date: {self.ctx.run_date or 'N/A'}",
            f"Symbols: {len(self.ctx.symbols)}",
            f"Regime: {self.ctx.regime or 'N/A'}",
            f"Candidates: {len(self.ctx.candidates)}",
            f"Top 30: {len(self.ctx.top_30)}",
            f"Top 10: {len(self.ctx.top_10)}",
            f"Report: {self.ctx.report_path or 'N/A'}",
        ]
        if self.ctx.error_message:
            lines.append(f"Error: {self.ctx.error_message}")
        if self.ctx.phase_times:
            lines.append("")
            lines.append("Phase timings:")
            for phase, duration in self.ctx.phase_times.items():
                lines.append(f"  {phase}: {duration:.1f}s")
            total = sum(self.ctx.phase_times.values())
            lines.append(f"  Total: {total:.1f}s")
        return "\n".join(lines)

    def phase_status(self) -> Dict[str, str]:
        """Status of each phase."""
        result = {}
        for phase in ['phase0', 'phase1', 'phase2', 'phase3', 'phase4', 'phase5', 'phase6']:
            if phase in self.ctx.phase_times:
                result[phase] = f"done ({self.ctx.phase_times[phase]:.1f}s)"
            elif self.ctx.status == 'failed':
                result[phase] = 'skipped'
            else:
                result[phase] = 'pending'
        return result

    def candidate_breakdown(self) -> Dict[str, int]:
        """Candidates by strategy."""
        breakdown = {}
        for name, source in [('candidates', self.ctx.candidates), ('top_30', self.ctx.top_30), ('top_10', self.ctx.top_10)]:
            counts = {}
            for c in source:
                strategy = getattr(c, 'strategy', 'unknown')
                counts[strategy] = counts.get(strategy, 0) + 1
            breakdown[name] = counts
        return breakdown

    def debug_phase(self, phase: str) -> str:
        """Get detailed debug info for a specific phase."""
        data = self.ctx.get_phase_data(phase)
        if not data:
            return f"No phase data available for {phase}"
        lines = [f"Phase {phase} data:"]
        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"  {key}: {len(value)} items")
            elif isinstance(value, dict):
                lines.append(f"  {key}: {len(value)} keys")
            else:
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)
