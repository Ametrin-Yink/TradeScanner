"""Tests for screener v7.0 sector soft cap."""
import pytest
from core.screener import StrategyScreener
from core.strategies import StrategyMatch


class TestScreenerV7:
    """Test sector soft cap."""

    def test_sector_cap_limits_concentration(self):
        """Should limit each sector to max 4 candidates."""
        screener = StrategyScreener()

        # Create mock candidates all from same sector
        candidates = []
        for i in range(8):
            match = StrategyMatch(
                symbol=f'SYM{i}',
                strategy='MomentumBreakout',
                entry_price=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                confidence=80,
                match_reasons=['test'],
                technical_snapshot={'score': 10.0 - i * 0.5, 'sector': 'Technology'}
            )
            candidates.append(match)

        # Call _allocate_by_table with 8 slots
        allocation = {'A': 8}
        result = screener._allocate_by_table(candidates, allocation, 'neutral')

        # Should only have 4 due to sector cap
        assert len(result) <= 4, f"Should limit to 4 per sector, got {len(result)}"

    def test_sector_cap_allows_multiple_sectors(self):
        """Should allow up to 4 candidates from each sector."""
        screener = StrategyScreener()

        # Create mock candidates from 3 different sectors
        candidates = []
        sectors = ['Technology', 'Healthcare', 'Finance']

        for sector in sectors:
            for i in range(6):  # 6 candidates per sector
                match = StrategyMatch(
                    symbol=f'{sector[:3].upper()}{i}',
                    strategy='MomentumBreakout',
                    entry_price=100.0,
                    stop_loss=90.0,
                    take_profit=120.0,
                    confidence=80,
                    match_reasons=['test'],
                    technical_snapshot={'score': 10.0 - i * 0.5, 'sector': sector}
                )
                candidates.append(match)

        # Call _allocate_by_table with 18 slots (6 per sector * 3 sectors)
        allocation = {'A': 18}
        result = screener._allocate_by_table(candidates, allocation, 'neutral')

        # Should have exactly 12 (4 per sector * 3 sectors)
        assert len(result) == 12, f"Should have 12 candidates (4 per sector * 3 sectors), got {len(result)}"

        # Verify each sector has exactly 4
        from collections import Counter
        sector_counts = Counter(c.technical_snapshot.get('sector', 'Unknown') for c in result)
        for sector in sectors:
            assert sector_counts.get(sector, 0) == 4, f"Expected 4 {sector} candidates, got {sector_counts.get(sector, 0)}"

    def test_sector_cap_with_duplicate_symbols(self):
        """Should handle duplicate symbols correctly with sector cap."""
        screener = StrategyScreener()

        # Create mock candidates with same symbol in different strategies
        candidates = [
            StrategyMatch(
                symbol='SYM1',
                strategy='MomentumBreakout',
                entry_price=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                confidence=80,
                match_reasons=['test'],
                technical_snapshot={'score': 8.0, 'sector': 'Technology'}
            ),
            StrategyMatch(
                symbol='SYM1',
                strategy='PullbackEntry',
                entry_price=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                confidence=80,
                match_reasons=['test'],
                technical_snapshot={'score': 9.0, 'sector': 'Technology'}  # Higher score
            ),
        ]

        # Call _allocate_by_table
        allocation = {'A': 1, 'B': 1}
        result = screener._allocate_by_table(candidates, allocation, 'neutral')

        # Should only have 1 candidate (duplicate resolved, keeping higher score)
        assert len(result) == 1, f"Should have 1 candidate after duplicate resolution, got {len(result)}"
        assert result[0].technical_snapshot.get('score') == 9.0, "Should keep the candidate with higher score"

    def test_sector_cap_with_unknown_sector(self):
        """Should handle candidates with Unknown sector."""
        screener = StrategyScreener()

        # Create mock candidates with Unknown sector
        candidates = []
        for i in range(6):
            match = StrategyMatch(
                symbol=f'SYM{i}',
                strategy='MomentumBreakout',
                entry_price=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                confidence=80,
                match_reasons=['test'],
                technical_snapshot={'score': 10.0 - i * 0.5, 'sector': 'Unknown'}
            )
            candidates.append(match)

        # Call _allocate_by_table - Unknown sector should NOT count against cap
        allocation = {'A': 6}
        result = screener._allocate_by_table(candidates, allocation, 'neutral')

        # Unknown sector candidates should not be limited by sector cap
        # All 6 should pass (since Unknown doesn't count against cap)
        assert len(result) == 6, f"Unknown sector should not be limited, got {len(result)}"
