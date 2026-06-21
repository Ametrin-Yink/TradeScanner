"""Report generator - sector-first HTML reports with amber palette."""
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta

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
.bar-chart-wrap{margin-bottom:20px;max-width:600px}
.bar-chart{display:flex;flex-direction:column;gap:3px;width:100%}
.bar-item{display:flex;align-items:center;gap:6px;cursor:pointer;transition:filter .15s;padding:2px 0}
.bar-item:hover{filter:brightness(1.3)}
.bar-label{font-size:10px;color:var(--frost);width:100px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0}
.bar-fill{height:18px;border-radius:3px;min-width:3px;transition:width .3s ease}
.bar-pct{font-size:9px;font-weight:600;width:50px;text-align:right;flex-shrink:0}
.fold-toggle{cursor:pointer;user-select:none;transition:background .15s}.fold-toggle:hover{background:var(--gold-dim);border-radius:4px}.fold-toggle h3::before{content:'\\25BC\\00a0';font-size:9px;transition:transform .2s}.fold-toggle.collapsed h3::before{content:'\\25B6\\00a0'}.fold-body{overflow:hidden;transition:max-height .3s;max-height:5000px;opacity:1}.fold-body.hidden{max-height:0;opacity:0}
.chart-inline{display:none;margin-top:8px;padding:8px;background:var(--bg-root);border-radius:var(--radius);border:1px solid var(--divider)}
.chart-inline canvas{display:block;max-width:100%}
.sym-link{cursor:pointer;color:var(--gold);text-decoration:underline}
.sym-link:hover{color:#e8c865}
"""

BAR_CHART_JS = """<script>
function showTag(n){
  var id='tag-'+n.replace(/[^a-zA-Z0-9]/g,'-');
  var cards=document.querySelectorAll('.tag-card');
  for(var i=0;i<cards.length;i++){cards[i].style.display='none';}
  var el=document.getElementById(id);
  if(el){el.style.display='block';el.scrollIntoView({behavior:'smooth'});}
  var hint=document.getElementById('tag-hint');
  if(hint)hint.style.display='none';
}
var _ck=null;
function setChartApiKey(k){_ck=k;}
function _key(){return _ck||sessionStorage.getItem('tradescanner_api_key')||localStorage.getItem('tradescanner_api_key')||'';}

async function showChart(sym,tagName){
  var anchor='chart-'+tagName.replace(/[^a-zA-Z0-9]/g,'-');
  var container=document.getElementById(anchor);
  if(!container)return;
  container.style.display='block';
  container.scrollIntoView({behavior:'smooth'});
  container.innerHTML='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px"><span style="color:var(--gold);font-weight:600;font-size:13px">'+sym+'</span><span style="color:var(--ash);font-size:10px">loading...</span></div><canvas id="'+anchor+'-canvas" style="width:100%;height:400px"></canvas>';
  try{
    var resp=await fetch('/api/data/ohlc/'+sym,{headers:{'Authorization':'Bearer '+_key()}});
    var d=await resp.json();
    if(!d.data||d.data.length===0){container.innerHTML='';return;}
    drawCandles(anchor+'-canvas',d.data,d.supports||[],d.resistances||[],sym);
  }catch(e){container.innerHTML='<div style="color:var(--ember)">Chart load failed</div>';}
}

function drawCandles(canvasId,data,supports,resistances,sym){
  var c=document.getElementById(canvasId);if(!c)return;
  var ctx=c.getContext('2d');
  var W=c.parentNode.clientWidth||900;c.width=W;c.height=400;
  var H=c.height,margin={top:20,right:70,bottom:40,left:70};
  var pw=W-margin.left-margin.right,ph=H-margin.top-margin.bottom;
  ctx.fillStyle='#0b1019';ctx.fillRect(0,0,W,H);

  var curPrice=data[data.length-1].close;
  var cutoff=curPrice*0.50;
  var nearSupports=supports.filter(function(s){return curPrice-s<=cutoff;});
  var nearResistances=resistances.filter(function(r){return r-curPrice<=cutoff;});

  var prices=[];data.forEach(function(d){prices.push(d.high,d.low);});
  nearSupports.forEach(function(s){prices.push(s);});
  nearResistances.forEach(function(r){prices.push(r);});
  var minP=Math.min.apply(null,prices),maxP=Math.max.apply(null,prices);
  var range=maxP-minP||1;
  var barW=Math.max(1.5,(pw/data.length)*0.7);barW=Math.min(barW,8);

  ctx.strokeStyle='rgba(28,39,56,0.4)';ctx.lineWidth=0.5;
  for(var i=0;i<=5;i++){
    var y=margin.top+(ph/5)*i;
    ctx.beginPath();ctx.moveTo(margin.left,y);ctx.lineTo(W-margin.right,y);ctx.stroke();
    var price=maxP-(range/5)*i;
    ctx.fillStyle='#5d6d80';ctx.font='9px monospace';ctx.fillText(price.toFixed(1),W-margin.right+4,y+4);
  }
  ctx.fillStyle='#5d6d80';ctx.font='9px monospace';ctx.textAlign='center';
  for(var i=0;i<data.length;i+=Math.max(1,Math.floor(data.length/8))){
    var x=margin.left+i*(pw/data.length)+barW/2;
    ctx.fillText(data[i].date.slice(5),x,H-margin.bottom+16);
  }
  ctx.textAlign='start';

  for(var i=0;i<data.length;i++){
    var d=data[i],x=margin.left+i*(pw/data.length);
    var oy=margin.top+(maxP-d.open)/range*ph;
    var cy=margin.top+(maxP-d.close)/range*ph;
    var hy=margin.top+(maxP-d.high)/range*ph;
    var ly=margin.top+(maxP-d.low)/range*ph;
    var clr=d.close>=d.open?'#7ecb5a':'#e0553d';
    ctx.strokeStyle=clr;ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(x+barW/2,hy);ctx.lineTo(x+barW/2,ly);ctx.stroke();
    ctx.fillStyle=clr;
    var bh=Math.max(1,Math.abs(cy-oy));
    ctx.fillRect(x,Math.min(oy,cy),barW,bh);
  }

  ctx.setLineDash([]);
  for(var i=0;i<nearSupports.length;i++){
    var sy=margin.top+(maxP-nearSupports[i])/range*ph;
    ctx.strokeStyle='rgba(126,203,90,0.8)';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.moveTo(margin.left,sy);ctx.lineTo(W-margin.right,sy);ctx.stroke();
    ctx.fillStyle='#7ecb5a';ctx.font='bold 11px monospace';
    ctx.fillText('S'+i+': $'+nearSupports[i].toFixed(2),margin.left+2,sy-3);
  }
  for(var i=0;i<nearResistances.length;i++){
    var ry=margin.top+(maxP-nearResistances[i])/range*ph;
    ctx.strokeStyle='rgba(224,85,61,0.8)';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.moveTo(margin.left,ry);ctx.lineTo(W-margin.right,ry);ctx.stroke();
    ctx.fillStyle='#e0553d';ctx.font='bold 11px monospace';
    ctx.fillText('R'+i+': $'+nearResistances[i].toFixed(2),margin.left+2,ry-3);
  }

  var title=document.getElementById(canvasId).parentNode.querySelector('div');
  if(title)title.innerHTML='<span style="color:var(--gold);font-weight:600;font-size:13px">'+sym+'</span><span style="color:var(--ash);font-size:10px">S:'+nearSupports.length+' | R:'+nearResistances.length+'</span>';
}
</script>"""

BAR_CHART_HTML = """<div class="bar-chart-wrap"><div class="bar-chart">{bars}</div></div>"""

STATS_STRIP = """<div class="stats-strip"><span class="stats-item"><b>SPY</b> ${spy_price:.2f} <span class="{spy_cls}">{spy_5d:+.2f}% 5d</span></span><span class="stats-item"><b>VIX</b> {vix:.1f}</span><span class="stats-item">{regime}</span></div>"""

SECTOR_CARD = """<div class="card tag-card" id="tag-{anchor}" style="display:none">
<div class="card-header fold-toggle" onclick="this.classList.toggle('collapsed');this.nextElementSibling.classList.toggle('hidden')"><h3>{name}</h3><span class="badge {chg_cls}">{daily_change}</span></div>
<div class="fold-body"><div class="detail-row">{outlook}</div>
<div class="detail-row" style="margin-top:4px"><span class="detail-label">Drivers</span></div>
{drivers}
<div class="detail-row" style="margin-top:4px"><span class="detail-label">Risks</span></div>
{risks}
{highlights_html}
<div class="chart-inline" id="chart-{anchor}"></div>
</div></div>"""

HIGHLIGHT_ROW = """<tr><td class="sym sym-link" onclick="showChart('{symbol}','{tag_name}')">{symbol}</td><td class="name">{name}</td><td class="num">${price:.2f}</td><td><span class="badge {reason_cls}">{reason}</span></td><td class="num">${entry:.2f}</td><td class="num {dist_cls}">{entry_dist}</td><td class="num">${stop:.2f}</td><td class="num">${target:.2f}</td><td class="num">{rr}</td><td class="num">{size}</td><td class="num">${cost}</td><td class="num">${risk_dollars}</td><td><span class="badge badge-neutral">{horizon}</span></td></tr>"""


class ReportGenerator:
    def __init__(self, reports_dir=None):
        self.reports_dir = Path(reports_dir) if reports_dir else REPORTS_DIR
        self.max_reports = settings.get('report', {}).get('max_reports', 15) if reports_dir is None else 999

    def _compute_diff(self, highlights, scan_date):
        yesterday = (datetime.strptime(scan_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_report = self.reports_dir / f"report_{yesterday}.html"
        if not yesterday_report.exists():
            return ""
        yesterday_text = yesterday_report.read_text(encoding='utf-8')
        yesterday_symbols = set(re.findall(r'class="sym[^"]*">([A-Z]+)', yesterday_text))
        today_symbols = set(h.symbol for h in highlights)
        parts = []
        new_picks = today_symbols - yesterday_symbols
        removed = yesterday_symbols - today_symbols
        unchanged = today_symbols & yesterday_symbols
        if new_picks: parts.append(f'+{len(new_picks)} new')
        if removed: parts.append(f'-{len(removed)} removed')
        if unchanged: parts.append(f'={len(unchanged)} unchanged')
        return f'<div class="header-meta" style="margin-top:4px">{" &middot; ".join(parts)} vs yesterday</div>' if parts else ""

    def generate_report(self, analysis_result: dict) -> str:
        import traceback
        market = analysis_result['market']
        sectors = analysis_result['sectors']
        focus = analysis_result.get('focus_summary')
        timestamp = analysis_result.get('timestamp', datetime.now().isoformat())
        scan_date = datetime.now().strftime('%Y-%m-%d')
        highlights_count = sum(len(s.highlights) for s in sectors)
        logger.info(f"ReportGenerator.generate_report called: date={scan_date} sectors={len(sectors)} picks={highlights_count} caller={traceback.extract_stack()[-3].filename}:{traceback.extract_stack()[-3].lineno}")
        html = self._build_html(market, sectors, focus, timestamp, scan_date)
        report_path = self.reports_dir / f"report_{scan_date}.html"
        report_path.write_text(html, encoding='utf-8')
        logger.info(f"Report generated: {report_path}")
        self._cleanup_old_reports()
        return str(report_path)

    def _build_html(self, market, sectors, focus, timestamp, scan_date=None) -> str:
        parts = ['<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>TradeScanner &middot; ', market.date, '</title><style>', STYLE, '</style></head><body>']

        total_stocks = len(set(h.symbol for s in sectors for h in s.highlights))
        all_highlights = [h for s in sectors for h in s.highlights]
        parts.append(f'<div class="header"><div><h1>TradeScanner</h1><div class="header-meta">{market.date} &middot; {len(sectors)} tags &middot; {total_stocks} picks</div>')
        if scan_date:
            parts.append(self._compute_diff(all_highlights, scan_date))
        parts.append('</div><div class="header-meta" style="text-align:right;font-size:10px">' + timestamp[:16] + '</div></div>')

        # Bar Chart (horizontal)
        max_chg = max(abs(s.daily_change) for s in sectors if s.daily_change is not None) or 1
        bars = []
        for s in sectors:
            chg = s.daily_change or 0
            width_pct = max(abs(chg) / max(max_chg, 0.01) * 100, 3)
            bg = "var(--volt)" if chg >= 0 else "var(--ember)"
            pct_clr = "var(--volt)" if chg >= 0 else "var(--ember)"
            sign = '+' if chg >= 0 else ''
            bars.append(f'<div class="bar-item" onclick="showTag(\'{s.name}\')" title="{s.name}: {sign}{chg:.2f}%"><span class="bar-label">{s.name}</span><div class="bar-fill" style="width:{width_pct:.0f}%;background:{bg}"></div><span class="bar-pct" style="color:{pct_clr}">{sign}{chg:.1f}%</span></div>')
        parts.append(BAR_CHART_HTML.format(bars=''.join(bars)))
        parts.append(BAR_CHART_JS)

        # Stats Strip
        spy_cls = 'up' if market.spy_change_5d >= 0 else 'down'
        parts.append(STATS_STRIP.format(spy_price=market.spy_price, spy_5d=market.spy_change_5d, spy_cls=spy_cls, vix=market.vix, regime=market.regime))

        # Market Overview
        if market.reasoning:
            parts.append(f'<div class="card"><div class="detail-row">{market.reasoning}</div>')
            if market.macro_drivers:
                parts.append('<div class="detail-label" style="margin-top:6px">Drivers</div>')
                for d in market.macro_drivers[:2]:
                    txt = d['text'] if isinstance(d, dict) else d
                    parts.append(f'<span class="driver">{txt}</span>')
            if market.risks:
                parts.append('<div class="detail-label" style="margin-top:6px">Risks</div>')
                for r in market.risks[:1]:
                    txt = r['text'] if isinstance(r, dict) else r
                    parts.append(f'<span class="risk">{txt}</span>')
            parts.append('</div>')

        # Positioning
        if focus and (focus.focus_sectors or focus.avoid_sectors):
            parts.append('<div class="positioning">')
            parts.append(f'<div class="pos-focus"><div class="pos-label">Focus</div><div class="pos-sectors">{", ".join(focus.focus_sectors or [])}</div></div>')
            parts.append(f'<div class="pos-avoid"><div class="pos-label">Avoid</div><div class="pos-sectors">{", ".join(focus.avoid_sectors or [])}</div></div>')
            parts.append('</div>')
            if focus.reasoning:
                parts.append(f'<div class="pos-reason" style="margin:-8px 0 16px 0;font-size:11px;color:var(--ash)">{focus.reasoning}</div>')

        # Tag Details
        parts.append('<h2>Tag Details</h2>')
        parts.append('<div id="tag-hint" style="color:var(--ash);font-size:12px;margin-bottom:12px">Click a bar above to see tag details</div>')
        reason_map = {'Near Resistance': 'badge-neutral', 'Near Support': 'badge-neutral', 'Breakout': 'badge-up', 'Strong Momentum': 'badge-up', 'Good R/R': 'badge-up'}
        for s in sectors:
            chg = s.daily_change
            chg_str = f"{chg:+.2f}%" if chg is not None else "--"
            chg_cls = 'badge-up' if (chg or 0) >= 0 else 'badge-down'
            anchor = re.sub(r'[^a-zA-Z0-9]', '-', s.name)

            drivers_html = ''
            for d in (s.key_drivers or []):
                txt = d['text'] if isinstance(d, dict) else d
                drivers_html += f'<span class="driver">{txt}</span>'
            risks_html = ''
            for r in (s.risks or []):
                txt = r['text'] if isinstance(r, dict) else r
                risks_html += f'<span class="risk">{txt}</span>'

            highlights_html = ''
            if s.highlights:
                def build_row(h):
                    if h.reason == 'Strong Momentum':
                        rs_val = getattr(h, 'rs_percentile', None)
                        if rs_val is not None:
                            n = int(rs_val)
                            sfx = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
                            reason_display = f"Strong Momentum (RS {n}{sfx})"
                        else:
                            reason_display = h.reason
                    else:
                        reason_display = h.reason
                    rr_str = f"{h.rr:.1f}x" if h.rr > 0 else "--"
                    size_str = str(getattr(h, 'position_size', 0))
                    cost_str = f"{getattr(h, 'position_cost', 0):,.0f}"
                    risk_str = f"{getattr(h, 'risk_dollars', 0):,.0f}"
                    horizon_str = getattr(h, 'time_horizon', '--')
                    dist_pct = getattr(h, 'entry_distance_pct', 0)
                    dist_str = f"{dist_pct:.0f}%" if dist_pct > 0.5 else "now"
                    dist_cls = 'up' if dist_pct <= 2 else ('dim' if dist_pct <= 5 else 'down')
                    return HIGHLIGHT_ROW.format(
                        symbol=h.symbol, tag_name=s.name, name=h.name or h.symbol, price=h.price,
                        reason=reason_display, reason_cls=reason_map.get(h.reason, 'badge-neutral'),
                        entry=h.entry, entry_dist=dist_str, dist_cls=dist_cls,
                        stop=h.stop, target=h.target, rr=rr_str,
                        size=size_str, cost=cost_str, risk_dollars=risk_str, horizon=horizon_str)

                active_threshold = 0.05  # matches portfolio_config.yaml active_entry_threshold
                active = [h for h in s.highlights if getattr(h, 'entry_distance_pct', 0) <= active_threshold * 100]
                watch = [h for h in s.highlights if getattr(h, 'entry_distance_pct', 0) > active_threshold * 100]

                table_header = '<table style="margin-top:8px"><thead><tr><th>Symbol</th><th>Name</th><th>Price</th><th>Reason</th><th>Entry</th><th>Dist</th><th>Stop</th><th>Target</th><th>R/R</th><th>Size</th><th>Cost</th><th>Risk</th><th>Horizon</th></tr></thead><tbody>'

                parts_html = []
                if active:
                    parts_html.append(f'<div style="margin-top:8px;font-size:10px;color:var(--volt);text-transform:uppercase;letter-spacing:.05em">Active Setups ({len(active)})</div>')
                    parts_html.append(table_header + ''.join(build_row(h) for h in active) + '</tbody></table>')
                if watch:
                    parts_html.append(f'<div style="margin-top:12px;font-size:10px;color:var(--ash);text-transform:uppercase;letter-spacing:.05em">Pullback Watch ({len(watch)})</div>')
                    parts_html.append(table_header + ''.join(build_row(h) for h in watch) + '</tbody></table>')
                highlights_html = ''.join(parts_html)

            outlook_html = s.outlook
            if not s.outlook or s.outlook == f"{s.name} sector: no AI analysis available.":
                outlook_html = '<span style="color:var(--ash);font-style:italic">AI analysis unavailable -- using fallback data</span>'

            parts.append(SECTOR_CARD.format(
                name=s.name, anchor=anchor, chg_cls=chg_cls, daily_change=chg_str,
                outlook=outlook_html,
                drivers=drivers_html or '<span class="dim">--</span>',
                risks=risks_html or '<span class="dim">--</span>',
                highlights_html=highlights_html))

        # Track AI status
        ai_errors = sum(1 for s in sectors if 'unavailable' in (s.outlook or ''))
        ai_status = f"AI: {len(sectors) - ai_errors}/{len(sectors)} sectors OK"
        # Add cost total from audit log
        parts.append(f'<div class="footer">TradeScanner &middot; {timestamp[:16]} &middot; {ai_status}</div>')
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
