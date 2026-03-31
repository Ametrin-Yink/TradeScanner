"""Tests for AI confidence scorer with sector concentration penalty."""
import pytest
from unittest.mock import Mock, patch

from core.ai_confidence_scorer import AIConfidenceScorer, ScoredCandidate
from core.screener import StrategyMatch


@pytest.fixture
def scorer():
    """Create AI confidence scorer instance."""
    with patch('core.ai_confidence_scorer.settings') as mock_settings:
        mock_settings.get_secret.return_value = 'test-api-key'
        mock_settings.get.return_value = {}
        return AIConfidenceScorer()


@pytest.fixture
def mock_candidates_same_sector():
    """Create 5 candidates all from Technology sector."""
    candidates = []
    for i, symbol in enumerate(['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META']):
        candidates.append(StrategyMatch(
            symbol=symbol,
            strategy='Momentum',
            entry_price=150.0 + i,
            stop_loss=145.0 + i,
            take_profit=160.0 + i,
            confidence=80,
            match_reasons=[f"Sector: Technology"],
            technical_snapshot={'sector': 'Technology', 'score': 12.5}
        ))
    return candidates


@pytest.fixture
def mock_candidates_mixed_sectors():
    """Create 5 candidates from different sectors."""
    sectors = [
        ('AAPL', 'Technology'),
        ('JPM', 'Financials'),
        ('XOM', 'Energy'),
        ('JNJ', 'Health Care'),
        ('WMT', 'Consumer Staples')
    ]
    candidates = []
    for i, (symbol, sector) in enumerate(sectors):
        candidates.append(StrategyMatch(
            symbol=symbol,
            strategy='Momentum',
            entry_price=150.0 + i,
            stop_loss=145.0 + i,
            take_profit=160.0 + i,
            confidence=80,
            match_reasons=[f"Sector: {sector}"],
            technical_snapshot={'sector': sector, 'score': 12.5}
        ))
    return candidates


@pytest.fixture
def mock_candidates_two_per_sector():
    """Create 6 candidates with 2 from each of 3 sectors."""
    sectors = [
        ('AAPL', 'Technology'),
        ('MSFT', 'Technology'),
        ('JPM', 'Financials'),
        ('BAC', 'Financials'),
        ('XOM', 'Energy'),
        ('CVX', 'Energy')
    ]
    candidates = []
    for i, (symbol, sector) in enumerate(sectors):
        candidates.append(StrategyMatch(
            symbol=symbol,
            strategy='Momentum',
            entry_price=150.0 + i,
            stop_loss=145.0 + i,
            take_profit=160.0 + i,
            confidence=80,
            match_reasons=[f"Sector: {sector}"],
            technical_snapshot={'sector': sector, 'score': 12.5}
        ))
    return candidates


class TestSectorConcentrationPenalty:
    """Test sector concentration penalty logic."""

    def test_extract_sector_from_snapshot(self, scorer):
        """Test extracting sector from technical_snapshot."""
        candidate = StrategyMatch(
            symbol='AAPL',
            strategy='Momentum',
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=80,
            match_reasons=["Sector: Technology"],
            technical_snapshot={'sector': 'Technology'}
        )

        sector = scorer._extract_sector(candidate)
        assert sector == 'Technology'

    def test_extract_sector_from_match_reasons(self, scorer):
        """Test extracting sector from match_reasons when snapshot lacks it."""
        candidate = StrategyMatch(
            symbol='AAPL',
            strategy='Momentum',
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=80,
            match_reasons=["Sector: Technology"],
            technical_snapshot={}
        )

        sector = scorer._extract_sector(candidate)
        assert sector == 'Technology'

    def test_extract_sector_unknown(self, scorer):
        """Test returning Unknown when sector not found."""
        candidate = StrategyMatch(
            symbol='AAPL',
            strategy='Momentum',
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=80,
            match_reasons=["Strong setup"],
            technical_snapshot={}
        )

        sector = scorer._extract_sector(candidate)
        assert sector == 'Unknown'

    def test_sector_count_calculation(self, scorer, mock_candidates_same_sector):
        """Test counting sector occurrences."""
        sector_counts = scorer._count_sectors(mock_candidates_same_sector)

        assert sector_counts['Technology'] == 5
        assert len(sector_counts) == 1

    def test_sector_count_mixed(self, scorer, mock_candidates_mixed_sectors):
        """Test counting with mixed sectors."""
        sector_counts = scorer._count_sectors(mock_candidates_mixed_sectors)

        assert sector_counts['Technology'] == 1
        assert sector_counts['Financials'] == 1
        assert sector_counts['Energy'] == 1
        assert sector_counts['Health Care'] == 1
        assert sector_counts['Consumer Staples'] == 1
        assert len(sector_counts) == 5

    def test_penalty_calculation_no_penalty(self, scorer):
        """Test penalty for 2 or fewer stocks in same sector."""
        # 2 stocks in same sector should have no penalty
        penalty = scorer._calculate_sector_penalty(2)
        assert penalty == 0.0

        # 1 stock in sector should have no penalty
        penalty = scorer._calculate_sector_penalty(1)
        assert penalty == 0.0

    def test_penalty_calculation_with_penalty(self, scorer):
        """Test penalty for 3+ stocks in same sector."""
        # 3 stocks: -5% penalty
        penalty = scorer._calculate_sector_penalty(3)
        assert penalty == 0.05

        # 4 stocks: -10% penalty
        penalty = scorer._calculate_sector_penalty(4)
        assert penalty == 0.10

        # 5 stocks: -15% penalty
        penalty = scorer._calculate_sector_penalty(5)
        assert penalty == 0.15

    def test_apply_penalty_to_confidence(self, scorer):
        """Test applying penalty to confidence score."""
        # 5 stocks same sector: -15% penalty
        adjusted = scorer._apply_sector_penalty(80, 5)
        # 80 * (1 - 0.15) = 80 * 0.85 = 68
        assert adjusted == 68

    def test_apply_no_penalty_to_confidence(self, scorer):
        """Test that no penalty is applied for 2 or fewer stocks."""
        adjusted = scorer._apply_sector_penalty(80, 2)
        assert adjusted == 80

        adjusted = scorer._apply_sector_penalty(80, 1)
        assert adjusted == 80

    def test_apply_penalty_rounding(self, scorer):
        """Test that penalty results are properly rounded."""
        # 90 * (1 - 0.05) = 85.5 -> should round to 86
        adjusted = scorer._apply_sector_penalty(90, 3)
        assert adjusted == 86

    @patch('core.ai_confidence_scorer.AIConfidenceScorer._score_batch')
    def test_score_candidates_applies_penalty(self, mock_score_batch, scorer, mock_candidates_same_sector):
        """Test that score_candidates applies sector penalty."""
        # Mock _score_batch to return initial scored candidates
        initial_scored = [
            ScoredCandidate(
                symbol=c.symbol,
                strategy=c.strategy,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                take_profit=c.take_profit,
                confidence=80,
                reasoning="Test",
                key_factors=["Test"],
                risk_factors=[],
                match_reasons=c.match_reasons,
                technical_snapshot=c.technical_snapshot
            )
            for c in mock_candidates_same_sector
        ]
        mock_score_batch.return_value = initial_scored

        result = scorer.score_candidates(mock_candidates_same_sector)

        # All 5 candidates in Technology should have penalty applied
        # -15% for 5 stocks: 80 * 0.85 = 68
        for candidate in result:
            assert candidate.confidence == 68

    @patch('core.ai_confidence_scorer.AIConfidenceScorer._score_batch')
    def test_score_candidates_no_penalty_mixed_sectors(self, mock_score_batch, scorer, mock_candidates_mixed_sectors):
        """Test that no penalty is applied when sectors are diversified."""
        initial_scored = [
            ScoredCandidate(
                symbol=c.symbol,
                strategy=c.strategy,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                take_profit=c.take_profit,
                confidence=80,
                reasoning="Test",
                key_factors=["Test"],
                risk_factors=[],
                match_reasons=c.match_reasons,
                technical_snapshot=c.technical_snapshot
            )
            for c in mock_candidates_mixed_sectors
        ]
        mock_score_batch.return_value = initial_scored

        result = scorer.score_candidates(mock_candidates_mixed_sectors)

        # All candidates should keep original confidence (no sector has > 2 stocks)
        for candidate in result:
            assert candidate.confidence == 80

    @patch('core.ai_confidence_scorer.AIConfidenceScorer._score_batch')
    def test_score_candidates_partial_penalty(self, mock_score_batch, scorer, mock_candidates_two_per_sector):
        """Test penalty when some sectors have exactly 2 stocks."""
        initial_scored = [
            ScoredCandidate(
                symbol=c.symbol,
                strategy=c.strategy,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                take_profit=c.take_profit,
                confidence=80,
                reasoning="Test",
                key_factors=["Test"],
                risk_factors=[],
                match_reasons=c.match_reasons,
                technical_snapshot=c.technical_snapshot
            )
            for c in mock_candidates_two_per_sector
        ]
        mock_score_batch.return_value = initial_scored

        result = scorer.score_candidates(mock_candidates_two_per_sector)

        # All candidates should have no penalty (max 2 per sector)
        for candidate in result:
            assert candidate.confidence == 80

    @patch('core.ai_confidence_scorer.AIConfidenceScorer._score_batch')
    def test_penalty_logging(self, mock_score_batch, scorer, mock_candidates_same_sector, caplog):
        """Test that penalty application is logged."""
        import logging
        caplog.set_level(logging.INFO)

        initial_scored = [
            ScoredCandidate(
                symbol='AAPL',
                strategy='Momentum',
                entry_price=150.0,
                stop_loss=145.0,
                take_profit=160.0,
                confidence=80,
                reasoning="Test",
                key_factors=["Test"],
                risk_factors=[],
                match_reasons=["Sector: Technology"],
                technical_snapshot={'sector': 'Technology'}
            )
        ]
        mock_score_batch.return_value = initial_scored

        scorer.score_candidates([mock_candidates_same_sector[0]])

        # Check that penalty was logged
        assert any("sector" in msg.lower() for msg in caplog.messages)


class TestScoredCandidate:
    """Test ScoredCandidate dataclass."""

    def test_scored_candidate_creation(self):
        """Test creating a ScoredCandidate."""
        candidate = ScoredCandidate(
            symbol='AAPL',
            strategy='Momentum',
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=80,
            reasoning="Strong setup",
            key_factors=["EMA alignment", "Volume confirmation"],
            risk_factors=["Market volatility"],
            match_reasons=["Broke above resistance"],
            technical_snapshot={'sector': 'Technology'}
        )

        assert candidate.symbol == 'AAPL'
        assert candidate.confidence == 80
