"""Sector-first market analysis using DeepSeek AI with web search.

Replaces the old strategy screening pipeline with a sector-driven approach.
Analyzes sectors daily and produces a sector-first report with AI-powered insights.
"""
import json
import logging
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict

from core.ai_client import chat
from core.constants import SECTOR_ETFS
from core.swing_detector import compute_stop_target, cluster_levels
from core.tag_manager import TagManager
from data.db import Database

logger = logging.getLogger(__name__)


@dataclass
class StockHighlight:
    """A single stock pick within a sector with technical reasoning."""
    symbol: str
    name: str
    price: float
    market_cap: float
    reason: str  # Near Resistance, Near Support, Breakout, Strong Momentum, Good R/R
    detail: str  # one-line setup description
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    rr: float = 0.0
    position_size: int = 0
    position_cost: float = 0.0
    risk_dollars: float = 0.0
    time_horizon: str = ''


@dataclass
class MarketOverview:
    """Overall market context for the daily report."""
    date: str
    regime: str
    confidence: int
    reasoning: str
    spy_price: float
    spy_change_5d: float
    vix: float
    vix_status: str
    top_sectors: List[str] = field(default_factory=list)
    bottom_sectors: List[str] = field(default_factory=list)
    macro_drivers: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


@dataclass
class SectorAnalysis:
    """Analysis of a single sector with AI outlook and stock highlights."""
    name: str
    etf: str
    stock_count: int
    daily_change: Optional[float]
    ret_3m: Optional[float]
    rs_percentile: Optional[float]
    trend: str
    above_ema50: Optional[bool]
    outlook: str
    key_drivers: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    highlights: List[StockHighlight] = field(default_factory=list)


@dataclass
class FocusSummary:
    """Which sectors to focus on and which to avoid, with AI reasoning."""
    focus_sectors: List[str]
    avoid_sectors: List[str]
    reasoning: str


_portfolio_config = None
def _load_portfolio_config():
    """Load portfolio config from YAML, with fallback defaults."""
    global _portfolio_config
    if _portfolio_config is None:
        config_path = Path(__file__).parent.parent / "config" / "portfolio_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                _portfolio_config = yaml.safe_load(f)
        else:
            _portfolio_config = {'account_value': 50000, 'risk_per_trade_pct': 0.01, 'max_position_pct': 0.20}
    return _portfolio_config


class SectorAnalyzer:
    """Full pipeline: market overview -> sector analysis -> stock highlights -> focus summary."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.tag_manager = TagManager()

    def analyze(self) -> Dict:
        """Run the full sector analysis pipeline.

        Returns:
            Dict with keys: market (MarketOverview), sectors (list of SectorAnalysis),
            focus_summary (FocusSummary), timestamp
        """
        market = self._analyze_market()
        sectors = self._analyze_all_sectors(market)
        self._refresh_sr_levels()
        self._find_stock_highlights(sectors)
        focus = self._generate_focus_summary(market, sectors)
        return {
            'market': market,
            'sectors': sectors,
            'focus_summary': focus,
            'timestamp': datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Step 1: Market Overview
    # ------------------------------------------------------------------

    def _analyze_market(self) -> MarketOverview:
        """Gather SPY/VIX data, regime info, and AI macro news analysis."""
        regime_data = self.db.load_regime() or {}
        spy = self.db.get_etf_cache('SPY') or {}
        vix = self.db.get_etf_cache('VIX') or {}

        date = datetime.now().strftime('%Y-%m-%d')
        regime = regime_data.get('regime', 'neutral')
        confidence = regime_data.get('ai_confidence', 50)
        reasoning = regime_data.get('ai_reasoning', '')

        spy_price = spy.get('current_price', 0.0) or 0.0
        spy_change_5d = spy.get('ret_5d', 0.0) or 0.0
        vix_val = vix.get('vix_current', spy.get('vix_current', 20.0)) or 20.0
        vix_status = vix.get('vix_status', 'neutral') or 'neutral'

        # Rank sectors by daily change for top/bottom
        sector_changes = []
        for s in self.tag_manager.get_tags(self.db):
            change = self.tag_manager.get_tag_daily_change(s['name'], self.db)
            if change is not None:
                sector_changes.append((s['name'], change))
        sector_changes.sort(key=lambda x: x[1], reverse=True)
        top_sectors = [s[0] for s in sector_changes[:3]]
        bottom_sectors = [s[0] for s in sector_changes[-3:]] if len(sector_changes) >= 3 else [s[0] for s in sector_changes]

        macro_drivers, risks = self._ai_macro_analysis()

        return MarketOverview(
            date=date,
            regime=regime,
            confidence=confidence,
            reasoning=reasoning,
            spy_price=spy_price,
            spy_change_5d=spy_change_5d,
            vix=vix_val,
            vix_status=vix_status,
            top_sectors=top_sectors,
            bottom_sectors=bottom_sectors,
            macro_drivers=macro_drivers,
            risks=risks,
        )

    def _ai_macro_analysis(self):
        """Call AI with web search for macro drivers and risks. Returns (drivers, risks)."""
        system_prompt = (
            "You are a US stock market analyst. Analyze the search results and return a JSON object "
            "with two keys: 'drivers' (list of 3-5 bullish/bearish macro drivers, each 1 sentence) "
            "and 'risks' (list of 2-3 key risks, each 1 sentence). No other text."
        )
        try:
            result = chat(
                messages=[{"role": "user", "content": "Summarize the key macro drivers and risks for the US stock market today."}],
                system=system_prompt,
                enable_search=True,
                search_query=f"US stock market today macro news {datetime.now().strftime('%B %Y')}",
                temperature=0.3,
            )
            if result:
                parsed = json.loads(result)
                drivers = parsed.get('drivers', [])
                risks = parsed.get('risks', [])
                if drivers or risks:
                    return drivers, risks
        except json.JSONDecodeError:
            logger.warning("AI macro analysis returned non-JSON response")
        except Exception as e:
            logger.warning("AI macro analysis failed: %s", e)
        return [], []

    # ------------------------------------------------------------------
    # Step 2: All Sectors (parallel)
    # ------------------------------------------------------------------

    def _analyze_all_sectors(self, market: MarketOverview) -> List[SectorAnalysis]:
        """Analyze all sectors in parallel."""
        sectors_raw = self.tag_manager.get_tags(self.db)
        if not sectors_raw:
            logger.warning("No sectors found in database")
            return []

        results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(self._analyze_sector, s, market): s['name']
                for s in sectors_raw
            }
            for future in as_completed(future_map):
                sector_name = future_map[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error("Sector analysis failed for '%s': %s", sector_name, e)
                    results.append(self._fallback_sector(sector_name))

        results.sort(key=lambda x: x.daily_change if x.daily_change is not None else -999, reverse=True)
        return results

    def _analyze_sector(self, sector_info: Dict, market: MarketOverview) -> SectorAnalysis:
        """Analyze a single sector with AI web search."""
        name = sector_info['name']
        etf = SECTOR_ETFS.get(name, '')
        stock_count = sector_info.get('stock_count', 0)
        daily_change = self.tag_manager.get_tag_daily_change(name, self.db)

        # Get benchmark data — try sector name first (synthetic benchmark), then ETF ticker
        ret_3m = None
        rs_percentile = None
        above_ema50 = None
        for lookup_key in (name, etf):
            if not lookup_key:
                continue
            data = self.db.get_etf_cache(lookup_key)
            if data:
                ret_3m = data.get('ret_3m') if ret_3m is None else ret_3m
                rs_percentile = data.get('rs_percentile') if rs_percentile is None else rs_percentile
                above_ema50 = data.get('above_ema50') if above_ema50 is None else above_ema50
                if ret_3m is not None and rs_percentile is not None and above_ema50 is not None:
                    break

        trend = self._determine_trend(daily_change, ret_3m, above_ema50)
        outlook, drivers, risks = self._ai_sector_analysis(name)

        return SectorAnalysis(
            name=name,
            etf=etf,
            stock_count=stock_count,
            daily_change=daily_change,
            ret_3m=ret_3m,
            rs_percentile=rs_percentile,
            trend=trend,
            above_ema50=above_ema50,
            outlook=outlook,
            key_drivers=drivers,
            risks=risks,
        )

    def _ai_sector_analysis(self, sector_name: str):
        """Call AI with web search for sector outlook. Returns (outlook, drivers, risks)."""
        system_prompt = (
            f"You are a sector analyst. Analyze search results about the {sector_name} sector. "
            "Return a JSON object with: "
            "'outlook' (2-3 sentence outlook), "
            "'drivers' (list of objects with 'text' and optional 'catalyst_date', each 1 sentence, "
            "  prefer specific events with dates over generic trends), "
            "'risks' (list of objects with 'text' and optional 'catalyst_date', each 1 sentence). "
            "If no specific catalysts exist, use the best available information. "
            "No other text."
        )
        try:
            result = chat(
                messages=[{"role": "user", "content": f"What is the outlook for the {sector_name} sector today?"}],
                system=system_prompt,
                enable_search=True,
                search_query=f"{sector_name} sector stocks news {datetime.now().strftime('%B %Y')}",
                temperature=0.3,
            )
            if result:
                parsed = json.loads(result)
                outlook = parsed.get('outlook', '')
                drivers_raw = parsed.get('drivers', [])
                risks_raw = parsed.get('risks', [])
                # Handle both string lists and object lists (with 'text' key)
                drivers = [d['text'] if isinstance(d, dict) else d for d in drivers_raw]
                risks = [r['text'] if isinstance(r, dict) else r for r in risks_raw]
                if outlook:
                    return outlook, drivers, risks
        except json.JSONDecodeError:
            logger.warning("AI sector analysis returned non-JSON for '%s'", sector_name)
        except Exception as e:
            logger.warning("AI sector analysis failed for '%s': %s", sector_name, e)
        return f"{sector_name} sector: no AI analysis available.", [], []

    def _fallback_sector(self, name: str) -> SectorAnalysis:
        """Create a fallback sector analysis when analysis fails entirely."""
        etf = SECTOR_ETFS.get(name, '')
        daily_change = self.tag_manager.get_tag_daily_change(name, self.db)
        sectors_raw = self.tag_manager.get_tags(self.db)
        stock_count = 0
        for s in sectors_raw:
            if s['name'] == name:
                stock_count = s.get('stock_count', 0)
                break
        return SectorAnalysis(
            name=name,
            etf=etf,
            stock_count=stock_count,
            daily_change=daily_change,
            ret_3m=None,
            rs_percentile=None,
            trend='neutral',
            above_ema50=None,
            outlook=f"{name} sector: analysis unavailable.",
        )

    @staticmethod
    def _determine_trend(daily_change: Optional[float], ret_3m: Optional[float], above_ema50: Optional[bool]) -> str:
        """Determine sector trend from available data points."""
        bullish_flags = 0
        if daily_change is not None and daily_change > 0.5:
            bullish_flags += 1
        if ret_3m is not None and ret_3m > 5:
            bullish_flags += 1
        if above_ema50:
            bullish_flags += 1
        if bullish_flags >= 2:
            return 'uptrend'
        if bullish_flags == 0 and daily_change is not None and daily_change < -0.5:
            return 'downtrend'
        return 'neutral'

    # ------------------------------------------------------------------
    # Step 2b: Refresh S/R levels for all stocks
    # ------------------------------------------------------------------

    def _refresh_sr_levels(self):
        """Compute fresh support/resistance levels for all pipeline stocks."""
        from core.swing_detector import compute_sr_for_symbol
        symbols = self.tag_manager.get_pipeline_stocks(None, self.db)
        logger.info(f"Computing S/R levels for {len(symbols)} stocks...")
        updated = 0
        for sym in symbols:
            try:
                s, r = compute_sr_for_symbol(self.db, sym)
                if s or r:
                    updated += 1
            except Exception:
                pass
        logger.info(f"S/R levels updated for {updated}/{len(symbols)} stocks")

    # ------------------------------------------------------------------
    # Step 3: Stock Highlights
    # ------------------------------------------------------------------

    def _find_stock_highlights(self, sector_analyses: List[SectorAnalysis]) -> None:
        """Apply technical rules to find stock highlights for each sector. Modifies in-place."""
        def _ord(n):
            if 10 <= n % 100 <= 20: return f"{n}th"
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
            return f"{n}{suffix}"

        for sector in sector_analyses:
            stocks = self.tag_manager.get_tag_stocks(sector.name, self.db)
            all_candidates = []
            used_symbols = set()

            for stock in stocks:
                symbol = stock['symbol']
                if symbol in used_symbols:
                    continue
                cache = self.db.get_tier1_cache(symbol)
                if not cache or not cache.get('current_price'):
                    continue

                price = cache['current_price']
                atr_pct = cache.get('atr_pct', 0.03) or 0.03
                atr = price * atr_pct
                rs_percentile = cache.get('rs_percentile', 0) or 0
                ema21 = cache.get('ema21')
                ema50 = cache.get('ema50')
                market_cap = stock.get('market_cap', 0) or 0
                name = stock.get('name', symbol) or symbol

                # Parse supports/resistances from cache
                try:
                    support_levels = json.loads(cache.get('supports', '[]') or '[]')
                    resistance_levels = json.loads(cache.get('resistances', '[]') or '[]')
                except (json.JSONDecodeError, TypeError):
                    support_levels = []
                    resistance_levels = []

                # Cluster raw levels into zones
                support_zones = cluster_levels(support_levels, tolerance=0.005)
                resistance_zones = cluster_levels(resistance_levels, tolerance=0.005)

                # Determine setup type
                high_60d = cache.get('high_60d')
                low_60d = cache.get('low_60d')
                volume_ratio = cache.get('volume_ratio', 1.0) or 1.0

                reason = None
                detail = None
                time_horizon = 'swing'

                if high_60d and price > high_60d and volume_ratio > 1.5:
                    reason = 'Breakout'
                    detail = f"Broke 60d high ${high_60d:.2f}, {volume_ratio:.1f}x vol"
                    time_horizon = 'swing'
                elif high_60d and price < high_60d and (high_60d - price) / price <= 0.02:
                    reason = 'Near Resistance'
                    dist = (high_60d - price) / price * 100
                    detail = f"{dist:.1f}% below 60d high ${high_60d:.2f}"
                    time_horizon = 'swing'
                elif low_60d and price > low_60d and (price - low_60d) / low_60d <= 0.02:
                    reason = 'Near Support'
                    dist = (price - low_60d) / low_60d * 100
                    detail = f"{dist:.1f}% above 60d low ${low_60d:.2f}"
                    time_horizon = 'swing'
                elif rs_percentile >= 80:
                    above = True
                    if ema21 and price <= ema21:
                        above = False
                    if ema50 and price <= ema50:
                        above = False
                    if above:
                        reason = 'Strong Momentum'
                        detail = f"RS {_ord(int(rs_percentile))} percentile, above EMAs"
                        time_horizon = 'position'
                elif low_60d and high_60d:
                    # Good R/R check — only if no other reason matched
                    stop_level = low_60d * 0.99
                    target_level = high_60d
                    if price > stop_level and target_level > price:
                        rr = (target_level - price) / (price - stop_level)
                        if rr >= 2.0:
                            reason = 'Good R/R'
                            detail = f"Stop at ${stop_level:.0f}, target ${target_level:.0f}"
                            time_horizon = 'swing'

                if reason is None:
                    continue

                # Compute technical stop and target
                ohlc_df = self.db.get_market_data_df(symbol)
                if ohlc_df is not None and len(ohlc_df) > 0:
                    ohlc_df = ohlc_df.rename(columns={
                        'open': 'Open', 'high': 'High', 'low': 'Low',
                        'close': 'Close', 'volume': 'Volume'
                    })
                stop, target, method = compute_stop_target(
                    price, atr, support_zones, resistance_zones,
                    df=ohlc_df,
                    time_horizon=time_horizon,
                )

                rr = round((target - price) / max(price - stop, 0.01), 1)
                rr = min(rr, 20.0)

                highlight = StockHighlight(
                    symbol=symbol, name=name, price=price,
                    market_cap=market_cap,
                    reason=reason, detail=detail,
                    entry=price, stop=stop, target=target, rr=rr,
                )

                # Store RS percentile and volume for sorting and report badge
                highlight.rs_percentile = rs_percentile
                highlight.volume_ratio = volume_ratio

                # Per-trade position sizing
                pconfig = _load_portfolio_config()
                risk_per_share = highlight.entry - highlight.stop
                max_risk_dollars = pconfig['account_value'] * pconfig['risk_per_trade_pct']
                position_size = int(max_risk_dollars / risk_per_share) if risk_per_share > 0 else 0
                position_cost = position_size * highlight.entry
                max_cost = pconfig['account_value'] * pconfig['max_position_pct']
                if position_cost > max_cost:
                    position_size = int(max_cost / highlight.entry)
                    position_cost = position_size * highlight.entry

                highlight.position_size = position_size
                highlight.position_cost = position_cost
                highlight.risk_dollars = position_size * risk_per_share

                # Set time horizon display
                horizon_map = {
                    'Breakout': 'Swing (5-20d)',
                    'Near Resistance': 'Swing (5-20d)',
                    'Near Support': 'Swing (5-20d)',
                    'Strong Momentum': 'Position (10-40d)',
                    'Good R/R': 'Swing (5-20d)',
                }
                highlight.time_horizon = horizon_map.get(reason, 'Swing (5-20d)')

                all_candidates.append(highlight)
                used_symbols.add(symbol)

            # Sort by R/R descending, select up to 3 with diverse reasons
            all_candidates.sort(
                key=lambda c: (c.rr, c.rs_percentile, c.volume_ratio),
                reverse=True,
            )
            selected = []
            used_reasons = set()
            # Pass 1: diverse reasons
            for c in all_candidates:
                if c.reason not in used_reasons and len(selected) < 3:
                    selected.append(c)
                    used_reasons.add(c.reason)
            # Pass 2: fill remaining by R/R
            for c in all_candidates:
                if c not in selected and len(selected) < 3:
                    selected.append(c)

            sector.highlights = selected

    # ------------------------------------------------------------------
    # Step 4: Focus Summary
    # ------------------------------------------------------------------

    def _generate_focus_summary(self, market: MarketOverview, sectors: List[SectorAnalysis]) -> FocusSummary:
        """Score sectors and rank into focus/avoid lists with AI reasoning."""
        if not sectors:
            return FocusSummary(focus_sectors=[], avoid_sectors=[], reasoning="No sector data available.")

        # Normalize ret_3m to [0, 1] range
        ret_3m_values = [s.ret_3m for s in sectors if s.ret_3m is not None]
        ret_min = min(ret_3m_values) if ret_3m_values else 0
        ret_max = max(ret_3m_values) if ret_3m_values else 0
        ret_range = ret_max - ret_min if ret_max != ret_min else 1

        scored = []
        for s in sectors:
            daily = s.daily_change if s.daily_change is not None else 0
            ret_norm = ((s.ret_3m or 0) - ret_min) / ret_range if ret_range > 0 else 0
            rs = (s.rs_percentile or 50) / 100.0
            uptrend_bonus = 1.0 if s.trend == 'uptrend' else 0.0
            # Balance: daily (25%), 3-month trend (35%), RS strength (30%), uptrend (10%)
            score = daily * 0.25 + ret_norm * 0.35 + rs * 0.30 + uptrend_bonus * 0.10
            scored.append((score, s.name))

        scored = self._apply_feedback(scored)

        scored.sort(key=lambda x: x[0], reverse=True)
        focus = [s[1] for s in scored[:3]]
        avoid = [s[1] for s in scored[-3:]]

        reasoning = self._ai_focus_reasoning(market, focus, avoid, scored[:5])
        return FocusSummary(focus_sectors=focus, avoid_sectors=avoid, reasoning=reasoning)

    def _apply_feedback(self, scored):
        """Adjust tag scores based on simulation outcomes. No-op if no data."""
        try:
            conn = self.db.get_connection()
            outcomes = conn.execute("""
                SELECT tag, outcome, COUNT(*) as cnt
                FROM simulation_positions
                WHERE outcome IN ('win', 'loss', 'expired')
                GROUP BY tag, outcome
            """).fetchall()

            tag_perf = {}
            for tag, outcome, cnt in outcomes:
                tag_perf.setdefault(tag, {'win': 0, 'total': 0})
                tag_perf[tag]['total'] += cnt
                if outcome == 'win':
                    tag_perf[tag]['win'] += cnt

            scored_out = list(scored)
            for i, (score, name) in enumerate(scored_out):
                perf = tag_perf.get(name)
                if perf and perf['total'] >= 5:
                    win_rate = perf['win'] / perf['total']
                    bonus = (win_rate - 0.5) * 0.10
                    scored_out[i] = (score + bonus, name)

            return scored_out
        except Exception:
            return scored

    def _ai_focus_reasoning(self, market: MarketOverview, focus: List[str], avoid: List[str], top5) -> str:
        """Call AI (no search) for 2-3 sentence focus summary reasoning."""
        data_str = (
            f"Market regime: {market.regime}. "
            f"SPY: ${market.spy_price:.2f} (5d: {market.spy_change_5d:+.1f}%). "
            f"VIX: {market.vix:.1f} ({market.vix_status}). "
            f"Focus sectors: {', '.join(focus)}. "
            f"Avoid sectors: {', '.join(avoid)}."
        )
        top5_str = "; ".join(f"{s[1]} (score={s[0]:.2f})" for s in top5)
        data_str += f" Top ranked: {top5_str}."

        system_prompt = (
            "You are a sector strategist. Given the market data and sector rankings, provide a 2-3 sentence "
            "reasoning for which sectors to focus on and which to avoid. Be specific and data-driven. "
            'Return as JSON: {"reasoning": "..."}. No other text.'
        )
        try:
            result = chat(
                messages=[{"role": "user", "content": data_str}],
                system=system_prompt,
                enable_search=False,
                temperature=0.3,
            )
            if result:
                parsed = json.loads(result)
                reasoning = parsed.get('reasoning', '')
                if reasoning:
                    return reasoning
        except json.JSONDecodeError:
            logger.warning("AI focus reasoning returned non-JSON")
        except Exception as e:
            logger.warning("AI focus reasoning failed: %s", e)

        return (
            f"Focus on {', '.join(focus)} sectors showing relative strength and favorable technicals. "
            f"Avoid {', '.join(avoid)} sectors which are underperforming across multiple metrics."
        )
