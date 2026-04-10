"""Validation utilities for strategy parameters."""
from typing import Dict, Any, Tuple, List


class ParameterValidator:
    """Validate strategy parameters against defined ranges."""

    # Define valid ranges for common parameters
    VALID_RANGES = {
        'min_dollar_volume': (1_000_000, 500_000_000),
        'min_atr_pct': (0.005, 0.1),
        'min_listing_days': (20, 252),
        'max_distance_from_level': (0.01, 0.1),
        'target_r_multiplier': (1.0, 5.0),
        'rsi_overbought': (70, 95),
        'rsi_oversold': (5, 30),
        'volume_climax_threshold': (2.0, 10.0),
        'vix_reject_threshold': (20, 50),
    }

    @classmethod
    def validate_param(cls, param_name: str, value: Any) -> Tuple[bool, str]:
        """
        Validate a single parameter.

        Returns:
            (is_valid, error_message)
        """
        if param_name not in cls.VALID_RANGES:
            return True, ""  # Unknown params pass validation

        min_val, max_val = cls.VALID_RANGES[param_name]

        if not isinstance(value, (int, float)):
            return False, f"{param_name} must be numeric"

        if value < min_val:
            return False, f"{param_name}={value} below minimum {min_val}"

        if value > max_val:
            return False, f"{param_name}={value} above maximum {max_val}"

        return True, ""

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate all parameters in a dict.

        Returns:
            (all_valid, list_of_errors)
        """
        errors = []

        for param_name, value in params.items():
            is_valid, error = cls.validate_param(param_name, value)
            if not is_valid:
                errors.append(error)

        return len(errors) == 0, errors

    @classmethod
    def get_valid_range(cls, param_name: str) -> Tuple[float, float]:
        """Get valid range for a parameter."""
        return cls.VALID_RANGES.get(param_name, (0, float('inf')))


def validate_strategy_config(strategy_name: str, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate a complete strategy configuration.

    Args:
        strategy_name: Name of the strategy
        config: Configuration dict

    Returns:
        (is_valid, list_of_errors)
    """
    validator = ParameterValidator()
    return validator.validate_params(config)
