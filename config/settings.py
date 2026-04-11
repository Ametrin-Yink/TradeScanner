"""Configuration management for trade scanner."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
REPORTS_DIR = WEB_DIR / "reports"
CHARTS_DIR = DATA_DIR / "charts"

# Ensure directories exist
for d in [DATA_DIR, WEB_DIR, REPORTS_DIR, CHARTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Default settings
DEFAULT_SETTINGS = {
    "scan": {
        "trigger_time": "06:00",
        "timezone": "America/New_York",
        "trading_days_only": True,
        "max_reports": 15,
    },
    "universe": {
        "default_stocks": "sp500,nasdaq100,dow",
        "max_stocks": 2000,
    },
    "screening": {
        "candidates_per_strategy": 5,
        "final_selection_count": 10,
        "min_adr": 0.03,
        "min_volume": 1000000,
    },
    "ai": {
        "api_base": "https://coding.dashscope.aliyuncs.com/v1",
        "model": "qwen-max",
        "analysis_mode": "tiered",
        "tavily_enabled": True,
    },
    "report": {
        "generate_charts": True,
        "chart_candles": 60,
        "web_port": 19801,
        "retention_days": 60,
        "base_url": "https://ametrin-maco.tail81da69.ts.net",
    },
    "notification": {
        "discord_enabled": True,
        "wechat_enabled": True,
    },
}

class Settings:
    """Settings manager with file persistence."""

    def __init__(self):
        self.settings_file = CONFIG_DIR / "settings.json"
        self.secrets_file = CONFIG_DIR / "secrets.json"
        self.stocks_file = CONFIG_DIR / "stocks.json"
        self._settings = self._load_settings()
        self._secrets = self._load_secrets()

    def _load_settings(self) -> dict:
        if self.settings_file.exists():
            with open(self.settings_file) as f:
                return json.load(f)
        return DEFAULT_SETTINGS.copy()

    def _load_secrets(self) -> dict:
        if self.secrets_file.exists():
            with open(self.secrets_file) as f:
                return json.load(f)
        return {}

    def get(self, key: str, default=None):
        return self._settings.get(key, default)

    def get_secret(self, key: str) -> str | None:
        """Get secret key supporting nested structure (e.g., 'tavily.api_key')."""
        if '.' in key:
            parts = key.split('.')
            value = self._secrets.get(parts[0], {})
            for part in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
        return self._secrets.get(key)

    def set(self, key: str, value):
        self._settings[key] = value
        self._save()

    def _save(self):
        with open(self.settings_file, 'w') as f:
            json.dump(self._settings, f, indent=2)

settings = Settings()
