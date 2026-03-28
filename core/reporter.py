"""Report generator - create HTML reports with charts."""
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict

import pandas as pd

from core.analyzer import AnalyzedOpportunity
from core.fetcher import DataFetcher
from core.plotly_charts import generate_static_plotly_chart
from config.settings import settings, REPORTS_DIR, CHARTS_DIR

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate HTML reports with K-line charts."""

    def __init__(self, fetcher: Optional[DataFetcher] = None):
        """Initialize report generator."""
        self.fetcher = fetcher or DataFetcher()
        self.reports_dir = REPORTS_DIR
        self.charts_dir = CHARTS_DIR
        self.max_reports = settings.get('report', {}).get('max_reports', 15)
        self.retention_days = settings.get('report', {}).get('retention_days', 15)

    def generate_report(
        self,
        opportunities: List[AnalyzedOpportunity],
        market_sentiment: str,
        total_stocks: int,
        success_count: int,
        fail_count: int,
        fail_symbols: List[str],
        all_candidates: List = None,
        sentiment_result: Dict = None
    ) -> str:
        """
        Generate full HTML report.

        Args:
            opportunities: List of analyzed opportunities
            market_sentiment: Market sentiment string
            total_stocks: Total stocks scanned
            success_count: Successfully fetched stocks
            fail_count: Failed stocks
            fail_symbols: List of failed symbols
            all_candidates: List of all candidates
            sentiment_result: Full sentiment analysis result with reasoning

        Returns:
            Path to generated report
        """
        scan_date = datetime.now().strftime('%Y-%m-%d')
        scan_time = datetime.now().strftime('%H:%M:%S')

        # Generate charts
        chart_paths = self._generate_charts(opportunities)

        # Build HTML
        html = self._build_html(
            opportunities=opportunities,
            all_candidates=all_candidates or [],
            market_sentiment=market_sentiment,
            sentiment_result=sentiment_result or {},
            scan_date=scan_date,
            scan_time=scan_time,
            total_stocks=total_stocks,
            success_count=success_count,
            fail_count=fail_count,
            fail_symbols=fail_symbols,
            chart_paths=chart_paths
        )

        # Save report
        report_filename = f"report_{scan_date}.html"
        report_path = self.reports_dir / report_filename

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        logger.info(f"Report generated: {report_path}")

        # Cleanup old reports
        self._cleanup_old_reports()

        return str(report_path)

    def _generate_charts(
        self,
        opportunities: List[AnalyzedOpportunity]
    ) -> Dict[str, str]:
        """Generate K-line charts for top opportunities."""
        chart_paths = {}

        for opp in opportunities[:10]:  # Top 10 only
            try:
                chart_path = self._generate_kline_chart(opp)
                if chart_path:
                    chart_paths[opp.symbol] = chart_path
            except Exception as e:
                logger.error(f"Failed to generate chart for {opp.symbol}: {e}")

        return chart_paths

    def _generate_kline_chart(self, opp: AnalyzedOpportunity) -> Optional[str]:
        """Generate static PNG chart for a single stock."""
        df = self.fetcher.fetch_stock_data(opp.symbol, period="3mo", interval="1d")

        if df is None or len(df) < 20:
            return None

        # Use static PNG chart (lighter, no 404 issues)
        chart_path = generate_static_plotly_chart(
            symbol=opp.symbol,
            df=df,
            entry_price=opp.entry_price,
            stop_loss=opp.stop_loss,
            take_profit=opp.take_profit,
            strategy=opp.strategy,
            output_dir=self.charts_dir
        )

        return chart_path

    def _build_html(
        self,
        opportunities: List[AnalyzedOpportunity],
        all_candidates: List,
        market_sentiment: str,
        sentiment_result: Dict,
        scan_date: str,
        scan_time: str,
        total_stocks: int,
        success_count: int,
        fail_count: int,
        fail_symbols: List[str],
        chart_paths: Dict[str, str]
    ) -> str:
        """Build HTML report content."""

        # Extract sentiment details
        sentiment_reasoning = sentiment_result.get('reasoning', '')
        sentiment_factors = sentiment_result.get('key_factors', [])
        sentiment_confidence = sentiment_result.get('confidence', 50)

        # Format sentiment details
        sentiment_factors_html = ""
        if sentiment_factors:
            sentiment_factors_html = '<div class="sentiment-factors">' + ''.join([f'<span class="factor">{f}</span>' for f in sentiment_factors[:5]]) + '</div>'

        sentiment_reasoning_html = f'<div class="sentiment-reasoning">{sentiment_reasoning}</div>' if sentiment_reasoning else ""

        sentiment_color = {
            'bullish': '#28a745',
            'bearish': '#dc3545',
            'neutral': '#ffc107',
            'watch': '#6c757d'
        }.get(market_sentiment, '#6c757d')

        # Build top opportunities section
        top_section = ""
        for i, opp in enumerate(opportunities[:10], 1):
            rrr = (opp.take_profit - opp.entry_price) / (opp.entry_price - opp.stop_loss) if opp.entry_price != opp.stop_loss else 0

            # Determine confidence color class
            if opp.confidence >= 70:
                conf_class = "confidence-high"
            elif opp.confidence >= 50:
                conf_class = "confidence-medium"
            else:
                conf_class = "confidence-low"

            chart_html = ""
            if opp.symbol in chart_paths:
                chart_relative_path = chart_paths[opp.symbol]
                # Use img tag for static PNG chart, positioned beside analysis
                chart_html = f'<img src="{chart_relative_path}" alt="{opp.symbol} Chart" class="chart-image">'

            risk_badges = "".join([f'<span class="badge badge-risk">{r}</span>' for r in opp.risk_factors[:3]])

            # Get tier and position size from technical_snapshot if available
            tier = getattr(opp, 'technical_snapshot', {}).get('tier', '')
            position_pct = getattr(opp, 'technical_snapshot', {}).get('position_pct', 0)
            score = getattr(opp, 'technical_snapshot', {}).get('score', 0) or getattr(opp, 'technical_snapshot', {}).get('total_score', 0)

            tier_badge = ""
            if tier:
                tier_colors = {'S': '#28a745', 'A': '#17a2b8', 'B': '#fd7e14'}
                tier_color = tier_colors.get(tier, '#6c757d')
                tier_badge = f'<span class="badge" style="background:{tier_color};color:white;margin-left:8px;">Tier {tier} ({position_pct*100:.0f}%)</span>'

            score_info = ""
            if score:
                score_info = f'<span class="badge" style="background:#6f42c1;color:white;margin-left:8px;">Score: {score:.0f}/15</span>'

            top_section += f"""
            <div class="opportunity">
                <div class="opp-header">
                    <span class="rank">#{i}</span>
                    <span class="symbol">{opp.symbol}</span>
                    <span class="strategy">{opp.strategy}</span>
                    <span class="confidence {conf_class}">{opp.confidence}%</span>
                    {tier_badge}
                    {score_info}
                </div>
                <div class="opp-details">
                    <div class="trade-levels">
                        <span class="level entry">Entry: ${opp.entry_price:.2f}</span>
                        <span class="level stop">Stop: ${opp.stop_loss:.2f}</span>
                        <span class="level target">Target: ${opp.take_profit:.2f}</span>
                        <span class="level rrr">R/R: {rrr:.1f}x</span>
                    </div>
                    <div class="analysis-row">
                        <div class="ai-analysis">
                            <h4>Analysis</h4>
                            <p><strong>Reasoning:</strong> {opp.ai_reasoning}</p>
                            <p><strong>Catalyst:</strong> {opp.catalyst}</p>
                            <p><strong>Risks:</strong> {risk_badges}</p>
                        </div>
                        {chart_html}
                    </div>
                </div>
            </div>
            """

        # Build runner-ups section (11-40) from all_candidates, excluding top 10
        # Get symbols in top 10 to exclude
        top_symbols = {opp.symbol for opp in opportunities[:10]}

        runners_section = ""
        runner_count = 0
        for cand in all_candidates:
            if cand.symbol in top_symbols:
                continue
            if runner_count >= 30:  # Max 30 additional candidates
                break
            runner_count += 1

            # Handle both AnalyzedOpportunity and StrategyMatch
            match_reasons = getattr(cand, 'match_reasons', [])
            runners_section += f"""
            <tr>
                <td>{cand.symbol}</td>
                <td>{cand.strategy}</td>
                <td>${cand.entry_price:.2f}</td>
                <td>{cand.confidence}%</td>
                <td>{', '.join(match_reasons[:2])}</td>
            </tr>
            """

        # Fail symbols
        fail_section = ", ".join(fail_symbols[:20]) if fail_symbols else "None"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trade Scanner Report - {scan_date}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
            background: #f8f9fa;
            color: #212529;
            line-height: 1.5;
            font-size: 14px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 16px; }}
        header {{
            background: #1a1a2e;
            color: white;
            padding: 20px 24px;
            margin-bottom: 20px;
            border-bottom: 3px solid #16213e;
        }}
        header h1 {{
            margin-bottom: 8px;
            font-size: 24px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        .meta {{
            opacity: 0.8;
            font-size: 13px;
            color: #a0a0a0;
        }}
        .sentiment {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            color: white;
            font-weight: 600;
            margin-top: 8px;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            background: {sentiment_color};
        }}
        .sentiment-details {{
            background: rgba(255,255,255,0.1);
            padding: 12px 16px;
            border-radius: 4px;
            margin-top: 12px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .sentiment-reasoning {{
            color: #e0e0e0;
            margin-bottom: 8px;
        }}
        .sentiment-factors {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
        }}
        .sentiment-factors .factor {{
            background: rgba(255,255,255,0.15);
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            color: #f0f0f0;
        }}
        .stats-compact {{
            font-size: 12px;
            color: #6c757d;
            margin-bottom: 16px;
            padding: 8px 0;
            border-bottom: 1px solid #dee2e6;
        }}
        .section-title {{
            font-size: 16px;
            font-weight: 600;
            margin: 24px 0 12px 0;
            color: #1a1a2e;
            border-bottom: 2px solid #dee2e6;
            padding-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .opportunity {{
            background: white;
            border-radius: 4px;
            padding: 16px;
            margin-bottom: 12px;
            border: 1px solid #dee2e6;
            border-left: 4px solid #1a1a2e;
        }}
        .opp-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        .rank {{
            font-size: 18px;
            font-weight: 700;
            color: #1a1a2e;
            width: 32px;
            text-align: center;
        }}
        .symbol {{ font-size: 20px; font-weight: 700; color: #1a1a2e; }}
        .strategy {{
            background: #e9ecef;
            color: #495057;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .confidence {{
            margin-left: auto;
            font-weight: 700;
            font-size: 16px;
        }}
        .confidence-high {{ color: #198754; }}
        .confidence-medium {{ color: #fd7e14; }}
        .confidence-low {{ color: #dc3545; }}
        .trade-levels {{
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }}
        .level {{
            padding: 4px 10px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: 600;
        }}
        .entry {{ background: #d1ecf1; color: #0c5460; }}
        .stop {{ background: #f8d7da; color: #721c24; }}
        .target {{ background: #d4edda; color: #155724; }}
        .rrr {{ background: #fff3cd; color: #856404; }}
        .ai-analysis {{
            background: #f8f9fa;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #e9ecef;
            flex: 1;
            min-width: 300px;
        }}
        .analysis-row {{
            display: flex;
            gap: 16px;
            align-items: flex-start;
            margin-top: 12px;
        }}
        .chart-image {{
            width: 400px;
            height: 300px;
            object-fit: contain;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            background: white;
        }}
        @media (max-width: 900px) {{
            .analysis-row {{
                flex-direction: column;
            }}
            .chart-image {{
                width: 100%;
                height: auto;
                max-height: 400px;
            }}
        }}
        .ai-analysis h4 {{
            margin-bottom: 8px;
            color: #1a1a2e;
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .ai-analysis p {{ margin-bottom: 6px; font-size: 13px; line-height: 1.5; }}
        .badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            background: #e9ecef;
            color: #495057;
            margin-right: 4px;
            margin-bottom: 4px;
        }}
        .badge-risk {{ background: #f8d7da; color: #721c24; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border: 1px solid #dee2e6;
            font-size: 13px;
        }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #dee2e6; }}
        th {{ background: #1a1a2e; color: white; font-weight: 600; font-size: 12px; text-transform: uppercase; }}
        tr:hover {{ background: #f8f9fa; }}
        .fail-symbols {{
            background: #f8f9fa;
            padding: 12px;
            border-radius: 4px;
            color: #6c757d;
            font-size: 13px;
            border: 1px solid #dee2e6;
        }}
        iframe {{ border-radius: 4px; border: 1px solid #dee2e6; margin-top: 12px; }}
        footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #dee2e6; text-align: center; color: #6c757d; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Trade Scanner Report</h1>
            <div class="meta">
                Date: {scan_date} | Time: {scan_time} ET | Scanned: {total_stocks} stocks
            </div>
            <div class="sentiment">Sentiment: {market_sentiment.upper()} ({sentiment_confidence}% confidence)</div>
            {sentiment_reasoning_html}
            {sentiment_factors_html}
        </header>

        <div class="stats-compact">
            Scanned: {total_stocks} | Success: {success_count} | Failed: {fail_count} | Top Picks: {len(opportunities[:10])}
        </div>

        <h2 class="section-title">Top 10 Opportunities</h2>
        {top_section}

        <h2 class="section-title">Additional Candidates (11-40)</h2>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Strategy</th>
                    <th>Entry</th>
                    <th>Confidence</th>
                    <th>Key Signals</th>
                </tr>
            </thead>
            <tbody>
                {runners_section}
            </tbody>
        </table>

        <h2 class="section-title">Failed Symbols</h2>
        <div class="fail-symbols">
            {fail_section}
        </div>

        <footer>
            <p>Trade Scanner v1.0 | Generated on {scan_date} {scan_time}</p>
            <p>For informational purposes only. Not financial advice.</p>
        </footer>
    </div>
</body>
</html>"""
        return html

    def _cleanup_old_reports(self):
        """Remove old reports beyond retention limit."""
        try:
            reports = sorted(
                self.reports_dir.glob('report_*.html'),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )

            # Keep only max_reports
            for old_report in reports[self.max_reports:]:
                old_report.unlink()
                logger.info(f"Removed old report: {old_report}")

            # Also cleanup charts older than retention_days
            cutoff = datetime.now() - timedelta(days=self.retention_days)
            for chart in self.charts_dir.glob('*.png'):
                if datetime.fromtimestamp(chart.stat().st_mtime) < cutoff:
                    chart.unlink()
            # Cleanup Plotly HTML charts
            for chart in self.charts_dir.glob('*.html'):
                if datetime.fromtimestamp(chart.stat().st_mtime) < cutoff:
                    chart.unlink()

        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
