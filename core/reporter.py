"""Report generator - sector-first HTML reports with amber palette."""
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from config.settings import settings, REPORTS_DIR

logger = logging.getLogger(__name__)

STYLE = """
:root{--ink:#0b1019;--paper:#141c26;--divider:#1c2738;--gold:#d4a853;--gold-dim:rgba(212,168,83,.12);--frost:#a8b9d1;--ash:#5d6d80;--ember:#e0553d;--volt:#7ecb5a;--radius:6px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--ink);color:var(--frost);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;max-width:1100px;margin:0 auto;line-height:1.5}
h1{font-size:20px;font-weight:600;letter-spacing:-.01em;margin-bottom:2px}
h2{font-size:15px;font-weight:600;margin:28px 0 10px;color:var(--gold)}
h3{font-size:13px;font-weight:600;margin:0}
.header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid var(--divider)}
.header-meta{font-size:11px;color:var(--ash)}
.badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.badge-up{background:rgba(126,203,90,.12);color:var(--volt)}
.badge-down{background:rgba(224,85,61,.12);color:var(--ember)}
.badge-neutral{background:rgba(93,109,128,.12);color:var(--ash)}
.card{background:var(--paper);border-radius:var(--radius);padding:14px 16px;margin-bottom:10px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.positioning{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.pos-focus{flex:1;min-width:200px;padding:12px 16px;background:var(--paper);border-radius:var(--radius);border-left:3px solid var(--volt)}
.pos-avoid{flex:1;min-width:200px;padding:12px 16px;background:var(--paper);border-radius:var(--radius);border-left:3px solid var(--ember)}
.pos-label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.pos-focus .pos-label{color:var(--volt)}.pos-avoid .pos-label{color:var(--ember)}
.pos-sectors{font-size:14px;font-weight:600}
.pos-reason{font-size:11px;color:var(--ash);margin-top:4px;line-height:1.4}
table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}
th{text-align:left;color:var(--ash);font-weight:500;padding:4px 8px;border-bottom:1px solid var(--divider);font-size:10px;text-transform:uppercase;letter-spacing:.05em}
td{padding:4px 8px;border-bottom:1px solid rgba(28,39,56,.5);font-family:'JetBrains Mono','Cascadia Code','Consolas',monospace;font-size:10px}
td.num{text-align:right}
td.name{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
tr:hover{background:rgba(212,168,83,.03)}
.up{color:var(--volt)}.down{color:var(--ember)}.dim{color:var(--ash)}
.footer{text-align:center;font-size:10px;color:var(--ash);margin-top:32px;padding:16px 0;border-top:1px solid var(--divider)}
.detail-row{margin:3px 0;font-size:11px;line-height:1.5}
.detail-label{color:var(--ash);font-size:9px;text-transform:uppercase;letter-spacing:.06em;margin-right:6px}
.driver,.risk{display:block;font-size:11px;line-height:1.5;padding:3px 0 3px 10px;margin:1px 0;border-left:2px solid}
.driver{border-left-color:rgba(212,168,83,.4)}.risk{border-left-color:rgba(224,85,61,.4)}
.stats-strip{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;padding:8px 0;margin-bottom:16px;border-bottom:1px solid var(--divider)}
.stats-item{color:var(--frost)}.stats-item b{color:var(--gold);font-weight:500}
/* Heatmap bar */
.heatmap-wrap{margin-bottom:20px}
.heatmap-bar{display:flex;height:36px;border-radius:4px;overflow:hidden;gap:1px;background:var(--divider)}
.heatmap-seg{display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:600;cursor:default;transition:filter .15s;min-width:0}
.heatmap-seg:hover{filter:brightness(1.3)}
.heatmap-labels{display:flex;font-size:10px;margin-top:4px;gap:1px;color:var(--ash)}
.heatmap-labels span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center}
/* Fold */
.fold-toggle{cursor:pointer;user-select:none;transition:background .15s}.fold-toggle:hover{background:var(--gold-dim);border-radius:4px}.fold-toggle h3::before{content:'\\25BC\\00a0';font-size:9px;transition:transform .2s}.fold-toggle.collapsed h3::before{content:'\\25B6\\00a0'}.fold-body{overflow:hidden;transition:max-height .3s ease,opacity .2s;max-height:5000px;opacity:1}.fold-body.hidden{max-height:0;opacity:0}
"""

HEATMAP_BAR = """<div class="heatmap-wrap"><div class="heatmap-bar">{segments}</div><div class="heatmap-labels">{labels}</div></div>"""

STATS_STRIP = """<div class="stats-strip"><span class="stats-item"><b>SPY</b> ${spy_price:.2f} <span class="{spy_cls}">{spy_5d:+.2f}% 5d</span></span><span class="stats-item"><b>VIX</b> {vix:.1f}</span><span class="stats-item">{regime}</span></div>"""

SECTOR_CARD = """<div class="card">
<div class="card-header fold-toggle" onclick="this.classList.toggle('collapsed');this.nextElementSibling.classList.toggle('hidden')"><h3>{name}</h3><span class="badge {chg_cls}">{daily_change}</span></div>
<div class="fold-body"><div class="detail-row">{outlook}</div>
<div class="detail-row" style="margin-top:4px"><span class="detail-label">Drivers</span></div>
{drivers}
<div class="detail-row" style="margin-top:4px"><span class="detail-label">Risks</span></div>
{risks}
{highlights_html}
</div></div>"""

HIGHLIGHT_ROW = """<tr><td class="sym">{symbol}</td><td class="name">{name}</td><td class="num">${price:.2f}</td><td><span class="badge {reason_cls}">{reason}</span></td><td class="num">${entry:.2f}</td><td class="num">${stop:.2f}</td><td class="num">${target:.2f}</td><td class="num">{rr}</td><td class="num">{size}</td><td class="num">${cost}</td><td class="num">${risk_dollars}</td><td><span class="badge badge-neutral">{horizon}</span></td></tr>"""


class ReportGenerator:
    def __init__(self):
        self.reports_dir = REPORTS_DIR
        self.max_reports = settings.get('report', {}).get('max_reports', 15)

    def _compute_diff(self, highlights, scan_date):
        """Compare today's picks to yesterday's report."""
        yesterday = (datetime.strptime(scan_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_report = self.reports_dir / f"report_{yesterday}.html"
        if not yesterday_report.exists():
            return ""

        yesterday_text = yesterday_report.read_text(encoding='utf-8')
        yesterday_symbols = set(re.findall(r'class="sym">([A-Z]+)', yesterday_text))
        today_symbols = set(h.symbol for h in highlights)

        new_picks = today_symbols - yesterday_symbols
        removed = yesterday_symbols - today_symbols
        unchanged = today_symbols & yesterday_symbols

        parts = []
        if new_picks:
            parts.append(f'+{len(new_picks)} new')
        if removed:
            parts.append(f'-{len(removed)} removed')
        if unchanged:
            parts.append(f'={len(unchanged)} unchanged')
        if parts:
            return f'<div class="header-meta" style="margin-top:4px">{" &middot; ".join(parts)} vs yesterday</div>'
        return ""

    def generate_report(self, analysis_result: dict) -> str:
        market = analysis_result['market']
        sectors = analysis_result['sectors']
        focus = analysis_result.get('focus_summary')
        timestamp = analysis_result.get('timestamp', datetime.now().isoformat())
        scan_date = datetime.now().strftime('%Y-%m-%d')

        html = self._build_html(market, sectors, focus, timestamp, scan_date)
        report_path = self.reports_dir / f"report_{scan_date}.html"
        report_path.write_text(html, encoding='utf-8')
        logger.info(f"Report generated: {report_path}")
        self._cleanup_old_reports()
        return str(report_path)

    def _build_html(self, market, sectors, focus, timestamp, scan_date=None) -> str:
        parts = ['<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>TradeScanner · ', market.date, '</title><style>', STYLE, '</style></head><body>']

        # Header
        total_stocks = len(set(h.symbol for s in sectors for h in s.highlights))
        all_highlights = [h for s in sectors for h in s.highlights]
        parts.append(f'<div class="header"><div><h1>TradeScanner</h1><div class="header-meta">{market.date} &middot; {len(sectors)} tags &middot; {total_stocks} picks</div>')
        if scan_date:
            parts.append(self._compute_diff(all_highlights, scan_date))
        parts.append('</div><div class="header-meta" style="text-align:right;font-size:10px">' + timestamp[:16] + '</div></div>')

        # Heatmap Bar
        max_chg = max(abs(s.daily_change) for s in sectors if s.daily_change is not None) or 1
        total_stocks_all = sum(s.stock_count for s in sectors) or 1
        segments = []
        labels = []
        for s in sectors:
            chg = s.daily_change or 0
            width_pct = max(s.stock_count / total_stocks_all * 100, 3)
            intensity = min(abs(chg) / max(max_chg, 0.01), 1.0)
            if chg >= 0:
                bg = f"rgba(126,203,90,{intensity * 0.7:.2f})"
                color = "#fff" if intensity > 0.5 else "var(--volt)"
            else:
                bg = f"rgba(224,85,61,{intensity * 0.7:.2f})"
                color = "#fff" if intensity > 0.5 else "var(--ember)"
            sign = '+' if chg >= 0 else ''
            title = f"{s.name}: {sign}{chg:.2f}%"
            seg = f'<div class="heatmap-seg" style="width:{width_pct:.1f}%;background:{bg};color:{color}" title="{title}">{sign}{chg:.1f}%</div>'
            segments.append(seg)
            labels.append(f'<span style="width:{width_pct:.1f}%">{s.name[:12]}</span>')
        parts.append(HEATMAP_BAR.format(segments=''.join(segments), labels=''.join(labels)))

        # Stats Strip
        spy_cls = 'up' if market.spy_change_5d >= 0 else 'down'
        parts.append(STATS_STRIP.format(
            spy_price=market.spy_price, spy_5d=market.spy_change_5d, spy_cls=spy_cls,
            vix=market.vix, regime=market.regime))

        # Market Overview (tight — narrative only)
        if market.reasoning:
            parts.append(f'<div class="card"><div class="detail-row">{market.reasoning}</div>')
            if market.macro_drivers:
                parts.append('<div class="detail-label" style="margin-top:6px">Drivers</div>')
                parts.extend(f'<span class="driver">{d}</span>' for d in market.macro_drivers[:2])
            if market.risks:
                parts.append('<div class="detail-label" style="margin-top:6px">Risks</div>')
                parts.extend(f'<span class="risk">{r}</span>' for r in market.risks[:1])
            parts.append('</div>')

        # Positioning (merged Focus + Avoid)
        if focus and (focus.focus_sectors or focus.avoid_sectors):
            parts.append('<div class="positioning">')
            parts.append(f'<div class="pos-focus"><div class="pos-label">Focus</div><div class="pos-sectors">{", ".join(focus.focus_sectors or [])}</div></div>')
            parts.append(f'<div class="pos-avoid"><div class="pos-label">Avoid</div><div class="pos-sectors">{", ".join(focus.avoid_sectors or [])}</div></div>')
            parts.append('</div>')
            if focus.reasoning:
                parts.append(f'<div class="pos-reason" style="margin:-8px 0 16px 0;font-size:11px;color:var(--ash)">{focus.reasoning}</div>')

        # Sector Details
        parts.append('<h2>Tag Details</h2>')
        for s in sectors:
            chg = s.daily_change
            chg_str = f"{chg:+.2f}%" if chg is not None else "--"
            chg_cls = 'badge-up' if (chg or 0) >= 0 else 'badge-down'

            drivers_html = ''.join(f'<span class="driver">{d}</span>' for d in (s.key_drivers or []))
            risks_html = ''.join(f'<span class="risk">{r}</span>' for r in (s.risks or []))

            highlights_html = ''
            if s.highlights:
                reason_map = {'Near Resistance': 'badge-neutral', 'Near Support': 'badge-neutral',
                              'Breakout': 'badge-up', 'Strong Momentum': 'badge-up', 'Good R/R': 'badge-up'}
                rows = []
                for h in s.highlights:
                    # Reason badge with embedded RS metric for Strong Momentum
                    if h.reason == 'Strong Momentum':
                        rs_val = getattr(h, 'rs_percentile', None)
                        if rs_val is not None:
                            rs_ord = f"{int(rs_val)}{'th' if 10<=int(rs_val)%100<=20 else {1:'st',2:'nd',3:'rd'}.get(int(rs_val)%10,'th')}"
                            reason_display = f"Strong Momentum (RS {rs_ord})"
                        else:
                            reason_display = h.reason
                    else:
                        reason_display = h.reason
                    rr_str = f"{h.rr:.1f}x" if h.rr > 0 else "--"
                    size_str = str(getattr(h, 'position_size', 0))
                    cost_str = f"{getattr(h, 'position_cost', 0):,.0f}"
                    risk_str = f"{getattr(h, 'risk_dollars', 0):,.0f}"
                    horizon_str = getattr(h, 'time_horizon', '--')
                    rows.append(HIGHLIGHT_ROW.format(
                        symbol=h.symbol, name=h.name or h.symbol, price=h.price,
                        reason=reason_display, reason_cls=reason_map.get(h.reason, 'badge-neutral'),
                        entry=h.entry, stop=h.stop, target=h.target, rr=rr_str,
                        size=size_str, cost=cost_str, risk_dollars=risk_str, horizon=horizon_str))
                highlights_html = '<table style="margin-top:8px"><thead><tr><th>Symbol</th><th>Name</th><th>Price</th><th>Reason</th><th>Entry</th><th>Stop</th><th>Target</th><th>R/R</th><th>Size</th><th>Cost</th><th>Risk</th><th>Horizon</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'

            if not s.outlook or s.outlook == f"{s.name} sector: no AI analysis available.":
                outlook_html = '<span style="color:var(--ash);font-style:italic">AI analysis unavailable -- using fallback data</span>'
            else:
                outlook_html = s.outlook
            parts.append(SECTOR_CARD.format(
                name=s.name, chg_cls=chg_cls, daily_change=chg_str,
                outlook=outlook_html,
                drivers=drivers_html or '<span class="dim">--</span>',
                risks=risks_html or '<span class="dim">--</span>',
                highlights_html=highlights_html))

        parts.append(f'<div class="footer">TradeScanner &middot; {timestamp[:16]}</div>')
        parts.append('</body></html>')
        return '\n'.join(parts)

    def _cleanup_old_reports(self):
        try:
            reports = sorted(self.reports_dir.glob('report_*.html'), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in reports[self.max_reports:]:
                old.unlink()
                logger.info(f"Removed old report: {old.name}")
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
