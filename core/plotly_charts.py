"""Chart generators - Plotly interactive and matplotlib static."""
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config.settings import CHARTS_DIR

logger = logging.getLogger(__name__)


def generate_plotly_chart(
    symbol: str,
    df: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    strategy: str,
    output_dir: Path = None
) -> Optional[str]:
    """Generate interactive Plotly candlestick chart."""
    try:
        if df is None or len(df) < 20:
            logger.warning(f"Insufficient data for {symbol}")
            return None

        df_plot = df.tail(60).copy()

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],
            subplot_titles=(f'{symbol} - {strategy}', 'Volume')
        )

        # Candlestick
        fig.add_trace(
            go.Candlestick(
                x=df_plot.index,
                open=df_plot['open'],
                high=df_plot['high'],
                low=df_plot['low'],
                close=df_plot['close'],
                name='Price',
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

        # Entry line
        fig.add_hline(y=entry_price, line_dash="dash", line_color="#2196f3",
                         annotation_text=f"Entry: ${entry_price:.2f}",
                         annotation_position="right", row=1, col=1)

        # Stop loss line
        fig.add_hline(y=stop_loss, line_dash="dash", line_color="#f44336",
                     annotation_text=f"Stop: ${stop_loss:.2f}",
                     annotation_position="right", row=1, col=1)

        # Take profit line
        fig.add_hline(y=take_profit, line_dash="dash", line_color="#4caf50",
                     annotation_text=f"Target: ${take_profit:.2f}",
                     annotation_position="right", row=1, col=1)

        # Volume bars
        colors = ['#26a69a' if df_plot['close'].iloc[i] >= df_plot['open'].iloc[i]
                  else '#ef5350' for i in range(len(df_plot))]
        fig.add_trace(
            go.Bar(x=df_plot.index, y=df_plot['volume'], marker_color=colors,
                  name='Volume', showlegend=False),
            row=2, col=1
        )

        fig.update_layout(
            title_text=f"{symbol} Trade Setup",
            title_x=0.5,
            xaxis_rangeslider_visible=False,
            template='plotly_white',
            height=600, width=900, showlegend=False,
            margin=dict(l=50, r=100, t=80, b=50)
        )

        fig.update_yaxes(title_text="Price ($)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        fig.update_xaxes(title_text="Date", row=2, col=1)

        output_dir = output_dir or CHARTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        chart_filename = f"{symbol}_{datetime.now().strftime('%Y%m%d')}.html"
        chart_path = output_dir / chart_filename

        fig.write_html(chart_path, include_plotlyjs='cdn', full_html=False,
                    div_id=f"chart_{symbol}")

        return str(chart_path.relative_to(output_dir.parent))

    except Exception as e:
        logger.error(f"Failed to generate Plotly chart for {symbol}: {e}")
        return None


def generate_static_plotly_chart(
    symbol: str,
    df: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    strategy: str,
    output_dir: Path = None
) -> Optional[str]:
    """Generate static chart using matplotlib (no Chrome required)."""
    try:
        if df is None or len(df) < 20:
            return None

        df_plot = df.tail(60).copy()

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(6, 4), dpi=100,
            gridspec_kw={'height_ratios': [3, 1]}, sharex=True
        )

        # Candlesticks
        for idx, (date, row) in enumerate(df_plot.iterrows()):
            color = '#26a69a' if row['close'] >= row['open'] else '#ef5350'
            ax1.plot([idx, idx], [row['low'], row['high']], color='black', linewidth=0.5)
            ax1.plot([idx, idx], [row['open'], row['close']], color=color, linewidth=2)

        # Horizontal lines
        ax1.axhline(y=entry_price, color='#2196f3', linestyle='--', linewidth=1.2)
        ax1.axhline(y=stop_loss, color='#f44336', linestyle='--', linewidth=1.2)
        ax1.axhline(y=take_profit, color='#4caf50', linestyle='--', linewidth=1.2)

        # Labels on the right
        ax1.text(len(df_plot)-1, entry_price, f' Entry ${entry_price:.2f}',
                color='#2196f3', fontsize=8, va='center')
        ax1.text(len(df_plot)-1, stop_loss, f' Stop ${stop_loss:.2f}',
                color='#f44336', fontsize=8, va='center')
        ax1.text(len(df_plot)-1, take_profit, f' Target ${take_profit:.2f}',
                color='#4caf50', fontsize=8, va='center')

        ax1.set_ylabel('Price')
        ax1.set_title(f'{symbol} - {strategy}', fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.set_xlim(-1, len(df_plot))

        # Volume
        colors = ['#26a69a' if df_plot['close'].iloc[i] >= df_plot['open'].iloc[i]
                  else '#ef5350' for i in range(len(df_plot))]
        ax2.bar(range(len(df_plot)), df_plot['volume'], color=colors, width=0.8)
        ax2.set_ylabel('Vol')

        # X-axis dates
        n_ticks = 5
        step = max(1, len(df_plot) // n_ticks)
        tick_pos = range(0, len(df_plot), step)
        ax2.set_xticks(tick_pos)
        ax2.set_xticklabels([df_plot.index[i].strftime('%m-%d') for i in tick_pos],
                           rotation=45, ha='right', fontsize=7)

        plt.tight_layout()

        output_dir = output_dir or CHARTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        chart_filename = f"{symbol}_{datetime.now().strftime('%Y%m%d')}.png"
        chart_path = output_dir / chart_filename

        plt.savefig(chart_path, dpi=120, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        return f"../data/charts/{chart_filename}"

    except Exception as e:
        logger.error(f"Failed to generate static chart for {symbol}: {e}")
        return None
