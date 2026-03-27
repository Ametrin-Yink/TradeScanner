"""Report generator - create HTML reports with charts."""
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict

import pandas as pd

from core.analyzer import AnalyzedOpportunity
from core.fetcher import DataFetcher
from core.plotly_charts import generate_plotly_chart
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
        all_candidates: List = None
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
        """Generate Plotly interactive chart for a single stock."""
        df = self.fetcher.fetch_stock_data(opp.symbol, period="3mo", interval="1d")

        if df is None or len(df) < 20:
            return None

        # Use Plotly to generate interactive chart
        chart_path = generate_plotly_chart(
            symbol=opp.symbol,
            df=df,
            entry_price=opp.entry_price,
            stop_loss=opp.stop_loss,
            take_profit=opp.take_profit,
            strategy=opp.strategy,
            output_dir=self.charts_dir
        )

        if chart_path:
            # Return URL path for iframe
            return f"/data/charts/{Path(chart_path).name}"
        return None

    def _build_html(
        self,
        opportunities: List[AnalyzedOpportunity],
        all_candidates: List,
        market_sentiment: str,
        scan_date: str,
        scan_time: str,
        total_stocks: int,
        success_count: int,
        fail_count: int,
        fail_symbols: List[str],
        chart_paths: Dict[str, str]
    ) -> str:
        """Build HTML report content."""

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

            chart_html = ""
            if opp.symbol in chart_paths:
                chart_relative_path = chart_paths[opp.symbol]
                # Use full URL for iframe
                chart_html = f'<iframe src="{chart_relative_path}" width="100%" height="620" frameborder="0" style="border: 1px solid #ddd; border-radius: 4px; margin-top: 15px;"></iframe>'

            risk_badges = "".join([f'<span class="badge badge-risk">{r}</span>' for r in opp.risk_factors[:3]])

            top_section += f"""
            <div class="opportunity">
                <div class="opp-header">
                    <span class="rank">#{i}</span>
                    <span class="symbol">{opp.symbol}</span>
                    <span class="strategy">{opp.strategy}</span>
                    <span class="confidence">{opp.confidence}% confidence</span>
                </div>
                <div class="opp-details">
                    <div class="trade-levels">
                        <span class="level entry">Entry: ${opp.entry_price:.2f}</span>
                        <span class="level stop">Stop: ${opp.stop_loss:.2f}</span>
                        <span class="level target">Target: ${opp.take_profit:.2f}</span>
                        <span class="level rrr">R/R: {rrr:.1f}x</span>
                    </div>
                    <div class="ai-analysis">
                        <h4>AI Analysis</h4>
                        <p><strong>Reasoning:</strong> {opp.ai_reasoning}</p>
                        <p><strong>Catalyst:</strong> {opp.catalyst}</p>
                        <p><strong>Risks:</strong> {risk_badges}</p>
                    </div>
                    {chart_html}
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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
        }}
        header h1 {{ margin-bottom: 10px; }}
        .meta {{ opacity: 0.9; font-size: 14px; }}
        .sentiment {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            color: white;
            font-weight: bold;
            margin-top: 10px;
            background: {sentiment_color};
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-box {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #667eea; }}
        .stat-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
        .opportunity {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .opp-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .rank {{
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
            width: 40px;
        }}
        .symbol {{ font-size: 24px; font-weight: bold; }}
        .strategy {{
            background: #e3f2fd;
            color: #1976d2;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .confidence {{
            margin-left: auto;
            color: #28a745;
            font-weight: 600;
        }}
        .trade-levels {{
            display: flex;
            gap: 15px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .level {{
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
        }}
        .entry {{ background: #e3f2fd; color: #1976d2; }}
        .stop {{ background: #ffebee; color: #c62828; }}
        .target {{ background: #e8f5e9; color: #2e7d32; }}
        .rrr {{ background: #fff3e0; color: #ef6c00; }}
        .ai-analysis {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
        }}
        .ai-analysis h4 {{ margin-bottom: 10px; color: #667eea; }}
        .ai-analysis p {{ margin-bottom: 8px; font-size: 14px; }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            background: #e0e0e0;
            margin-right: 5px;
        }}
        .badge-risk {{ background: #ffebee; color: #c62828; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #667eea; color: white; font-weight: 600; }}
        tr:hover {{ background: #f5f5f5; }}
        .section-title {{
            font-size: 20px;
            font-weight: bold;
            margin: 30px 0 15px 0;
            color: #333;
        }}
        .fail-symbols {{
            background: #ffebee;
            padding: 15px;
            border-radius: 8px;
            color: #c62828;
            font-size: 14px;
        }}
        img {{ border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📈 Trade Scanner Daily Report</h1>
            <div class="meta">
                Scan Date: {scan_date}<br>
                Scan Time: {scan_time} ET<br>
                Total Stocks Analyzed: {total_stocks}
            </div>
            <div class="sentiment">Market Sentiment: {market_sentiment.upper()}</div>
        </header>

        <div class="stats">
            <div class="stat-box">
                <div class="stat-value">{total_stocks}</div>
                <div class="stat-label">Total Scanned</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{success_count}</div>
                <div class="stat-label">Successful</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{fail_count}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{len(opportunities[:10])}</div>
                <div class="stat-label">Top Picks</div>
            </div>
        </div>

        <h2 class="section-title">🎯 Top 10 Opportunities</h2>
        {top_section}

        <h2 class="section-title">📋 Additional Candidates (11-40)</h2>
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

        <h2 class="section-title">⚠️ Failed Symbols</h2>
        <div class="fail-symbols">
            {fail_section}
        </div>

        <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #999; font-size: 12px;">
            <p>Trade Scanner v1.0 - Generated on {scan_date} {scan_time}</p>
            <p>This report is for informational purposes only. Not financial advice.</p>
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
