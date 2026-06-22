"""Portfolio configuration loader from YAML."""
import yaml
from pathlib import Path


def load_config() -> dict:
    """Load portfolio config from YAML, with fallback defaults."""
    config_path = Path(__file__).parent / "portfolio_config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}
