"""Portfolio configuration loader from YAML."""
import yaml
from pathlib import Path


def load_config() -> dict:
    """Load portfolio config from YAML, with fallback defaults."""
    config_path = Path(__file__).parent / "portfolio_config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {
        'account_value': 50000,
        'risk_per_trade_pct': 0.01,
        'max_position_pct': 0.20,
        'max_entry_distance_pct': 0.10,
        'active_entry_threshold': 0.05,
    }
