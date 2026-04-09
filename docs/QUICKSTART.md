# Pipeline Quick Start

## Running the Scanner

```bash
# Test scan
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Debug mode (verbose logging + pipeline summary)
python scheduler.py --test --symbols AAPL --debug

# Full workflow (production)
python scheduler.py
python scheduler.py --force  # skip trading day check
```

## New Architecture (Phase 1-4 restructure)

### Service Registry

```python
from core.services import ServiceRegistry
from core.services.providers import register_defaults

register_defaults()
db = ServiceRegistry.get('database')
```

### Strategy Plugins (no hardcoded imports)

```python
from core.strategies import create_strategy, STRATEGY_REGISTRY, StrategyType

s = create_strategy(StrategyType.A1)  # MomentumBreakout
s = create_strategy(StrategyType.B, config={'min_data_days': 100})  # config override
```

### Pipeline Engine

```python
from core.engine import PipelineOrchestrator, PipelineContext

ctx = PipelineContext(symbols=['AAPL'], run_date='2026-04-09')
pipeline = PipelineOrchestrator()
result = pipeline.run(ctx)
```

### Debug Inspector

```python
from core.debug import PipelineInspector

inspector = PipelineInspector(ctx)
print(inspector.summary())
print(inspector.phase_status())
print(inspector.candidate_breakdown())
```
