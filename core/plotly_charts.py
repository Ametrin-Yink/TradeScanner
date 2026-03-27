"""Plotly-based interactive chart generator."""
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
    """
    Generate interactive Plotly candlestick chart.

    Args:
        symbol: Stock symbol
        df: OHLCV DataFrame
        entry_price: Entry price level
        stop_loss: Stop loss level
        take_profit: Take profit level
        strategy: Strategy name
        output_dir: Output directory

    Returns:
        Path to saved HTML file or None
    """
    try:
        if df is None or len(df) < 20:
            logger.warning(f"Insufficient data for {symbol}")
            return None

        # Use last 60 candles
        df_plot = df.tail(60).copy()

        # Create subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],
            subplot_titles=(f'{symbol} - {strategy}', 'Volume')
        )

        # Add candlestick
        fig.add_trace(
            go.Candlestick(
                x=df_plot.index,
                open=df_plot['open'],
                high=df_plot['high'],
                low=df_plot['low'],
                close=df_plot['close'],
                name='Price',
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350',
                increasing_fillcolor='#26a69a',
                decreasing_fillcolor='#ef5350'
            ),
            row=1, col=1
        )

        # Add entry line
        fig.add_hline(
            y=entry_price,
            line_dash="dash",
            line_color="#2196f3",
            annotation_text=f"Entry: ${entry_price:.2f}",
            annotation_position="right",
            row=1, col=1
        )

        # Add stop loss line
        fig.add_hline(
            y=stop_loss,
            line_dash="dash",
            line_color="#f44336",
            annotation_text=f"Stop: ${stop_loss:.2f}",
            annotation_position="right",
            row=1, col=1
        )

        # Add take profit line
        fig.add_hline(
            y=take_profit,
            line_dash="dash",
            line_color="#4caf50",
            annotation_text=f"Target: ${take_profit:.2f}",
            annotation_position="right",
            row=1, col=1
        )

        # Add volume bars
        colors = ['#26a69a' if df_plot['close'].iloc[i] >= df_plot['open'].iloc[i]
                  else '#ef5350' for i in range(len(df_plot))]

        fig.add_trace(
            go.Bar(
                x=df_plot.index,
                y=df_plot['volume'],
                marker_color=colors,
                name='Volume',
                showlegend=False
            ),
            row=2, col=1
        )

        # Update layout
        fig.update_layout(
            title_text=f"{symbol} Trade Setup",
            title_x=0.5,
            xaxis_rangeslider_visible=False,
            template='plotly_white',
            height=600,
            width=900,
            showlegend=False,
            margin=dict(l=50, r=100, t=80, b=50)
        )

        # Update y-axes
        fig.update_yaxes(title_text="Price ($)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        fig.update_xaxes(title_text="Date", row=2, col=1)

        # Save as HTML
        output_dir = output_dir or CHARTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        chart_filename = f"{symbol}_{datetime.now().strftime('%Y%m%d')}.html"
        chart_path = output_dir / chart_filename

        fig.write_html(
            chart_path,
            include_plotlyjs='cdn',
            full_html=False,
            div_id=f"chart_{symbol}"
        )

        logger.info(f"Plotly chart saved: {chart_path}")
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
    """
    Generate static PNG chart using Plotly (requires kaleido).

    Args:
        symbol: Stock symbol
        df: OHLCV DataFrame
        entry_price: Entry price level
        stop_loss: Stop loss level
        take_profit: Take profit level
        strategy: Strategy name
        output_dir: Output directory

    Returns:
        Path to saved PNG file or None
    """
    try:
        if df is None or len(df) < 20:
            return None

        df_plot = df.tail(60).copy()

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3]
        )

        # Candlestick
        fig.add_trace(
            go.Candlestick(
                x=df_plot.index,
                open=df_plot['open'],
                high=df_plot['high'],
                low=df_plot['low'],
                close=df_plot['close'],
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

        # Horizontal lines
        fig.add_hline(y=entry_price, line_dash="dash", line_color="#2196f3", row=1, col=1)
        fig.add_hline(y=stop_loss, line_dash="dash", line_color="#f44336", row=1, col=1)
        fig.add_hline(y=take_profit, line_dash="dash", line_color="#4caf50", row=1, col=1)

        # Volume
        colors = ['#26a69a' if df_plot['close'].iloc[i] >= df_plot['open'].iloc[i]
                  else '#ef5350' for i in range(len(df_plot))]
        fig.add_trace(
            go.Bar(x=df_plot.index, y=df_plot['volume'], marker_color=colors),
            row=2, col=1
        )

        # Layout - smaller size for side-by-side display
        fig.update_layout(
            title=f"{symbol} - {strategy}",
            xaxis_rangeslider_visible=False,
            template='plotly_white',
            height=350,
            width=500,
            showlegend=False,
            margin=dict(l=40, r=40, t=40, b=40)
        )

        # Save as PNG
        output_dir = output_dir or CHARTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        chart_filename = f"{symbol}_{datetime.now().strftime('%Y%m%d')}.png"
        chart_path = output_dir / chart_filename

        fig.write_image(chart_path, scale=2)

        return f"../data/charts/{chart_filename}"

    except Exception as e:
        logger.error(f"Failed to generate static chart for {symbol}: {e}")
        return None
