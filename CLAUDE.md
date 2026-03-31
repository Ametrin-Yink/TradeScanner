# CLAUDE.md

Trade Scanner - Current State Reference

## Project Overview

Automated US stock trading opportunity scanner analyzing 517 US stocks daily using 6 trading strategies. Generates web-based reports with AI-powered analysis.

## Current Architecture (v3.0)

**6 Strategy Plugins** (`core/strategies/`):
| Strategy | File | Type | Description |
|----------|------|------|-------------|
| MomentumBreakout | momentum_breakout.py | Long | VCP + momentum with RS bonus |
| PullbackEntry | pullback_entry.py | Long | EMA pullback with 4D scoring |
| SupportBounce | support_bounce.py | Long | Upthrust & rebound |
| RangeShort | range_short.py | Short | Range breakdown |
| DoubleTopBottom | double_top_bottom.py | Both | Distribution/accumulation |
| CapitulationRebound | capitulation_rebound.py | Long | Capitulation reversal |

**Pipeline**:
- `fetcher.py` → `screener.py` → `analyzer.py` → `reporter.py`
- Database: SQLite (`data/stocks.db`)
- Web: Flask on port 19801

## Key Technical Decisions

- **Data**: yfinance (free), threads=False, 0.5s delay
- **AI**: Alibaba DashScope (OpenAI-compatible)
- **Scale**: 517 stocks, ~70-80 min first run, ~20-25 min cached
- **Charts**: matplotlib with Agg backend
- **Caching**: 150 trading days retained

## Scoring System

- **Unified**: 0-15 points, 4 dimensions per strategy
- **Tiers**: S (12+, 20%), A (9+, 10%), B (7+, 5%), C (<7, reject)
- **Linear interpolation** for boundary values

## Development Conventions

- Python 3.10+ with type hints
- API keys in `config/secrets.json` (nested: `dashscope.api_key`)
- Vectorized pandas operations
- Test: `python scheduler.py --test --symbols AAPL,MSFT,NVDA`

## Commands

```bash
# Test scan
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Full scan
python scheduler.py

# Web server
python api/server.py

# Check status
ss -tlnp | grep 19801
```

## Critical Patterns

**Strategy Plugin Interface**:
```python
class MyStrategy(BaseStrategy):
    NAME = "StrategyName"
    STRATEGY_TYPE = StrategyType.XXX
    DIMENSIONS = ['D1', 'D2', 'D3', 'D4']
    
    def filter(self, symbol, df) -> bool: ...
    def calculate_dimensions(self, symbol, df) -> List[ScoringDimension]: ...
    def calculate_entry_exit(self, symbol, df, dims, score, tier) -> Tuple[float, float, float]: ...
    def build_match_reasons(self, symbol, df, dims, score, tier) -> List[str]: ...
```

**Shared Utilities** (`core/scoring_utils.py`):
- `calculate_clv()`, `check_rsi_divergence()`, `check_exhaustion_gap()`
- `calculate_rs_score_weighted()`, `calculate_normalized_ema_slope()`

## Important Notes

- **kimi-k2.5**: No `response_format` support - use regex JSON extraction
- **yfinance**: Wikipedia blocks (403), use Slickcharts for stock lists
- **Memory**: Keep under 500MB, batch processing in 50s
- **Server**: Port 19801 only (security group restriction)
- **Formula Sync**: Update `策略描述.md` when modifying calculations
