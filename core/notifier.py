"""Discord and WeChat notification module."""
import logging
import json
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Send notifications to Discord via webhook."""

    def __init__(self, webhook_url: Optional[str] = None):
        """Initialize with webhook URL."""
        self.webhook_url = webhook_url

    def send_message(
        self,
        content: str,
        username: Optional[str] = "Trade Scanner",
        embeds: Optional[list] = None
    ) -> bool:
        """Send message to Discord webhook."""
        if not self.webhook_url:
            logger.warning("No Discord webhook URL configured")
            return False

        payload = {
            "username": username,
            "content": content[:2000]
        }

        if embeds:
            payload["embeds"] = embeds

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            logger.info(f"Discord message sent: {content[:100]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return False

    def send_scan_summary(
        self,
        scan_date: str,
        market_sentiment: str,
        top_opportunities: list,
        report_url: Optional[str] = None
    ) -> bool:
        """Send scan summary with rich embed."""
        opp_text = ""
        for i, opp in enumerate(top_opportunities[:5], 1):
            opp_text += f"**{i}. {opp.symbol}** ({opp.strategy}) - {opp.confidence}%\n"
            opp_text += f"   Entry: ${opp.entry_price:.2f} | Stop: ${opp.stop_loss:.2f}\n\n"

        embed = {
            "title": f"📊 Daily Scan Complete - {scan_date}",
            "description": f"Market Sentiment: **{market_sentiment.upper()}**",
            "color": self._sentiment_color(market_sentiment),
            "fields": [
                {
                    "name": "🎯 Top Opportunities",
                    "value": opp_text or "No opportunities found",
                    "inline": False
                }
            ],
            "footer": {
                "text": "Trade Scanner by AI CIO"
            }
        }

        if report_url:
            embed["fields"].append({
                "name": "📄 Full Report",
                "value": f"[View Report]({report_url})",
                "inline": False
            })

        return self.send_message(
            content=f"🚀 Daily scan complete! Found {len(top_opportunities)} opportunities.",
            embeds=[embed]
        )

    def _sentiment_color(self, sentiment: str) -> int:
        """Get Discord color code for sentiment."""
        colors = {
            "bullish": 0x00ff00,
            "bearish": 0xff0000,
            "neutral": 0x808080,
            "watch": 0xffa500
        }
        return colors.get(sentiment.lower(), 0x808080)


class WeChatNotifier:
    """Send notifications to WeChat Work via webhook."""

    def __init__(self, webhook_url: Optional[str] = None):
        """Initialize with webhook URL."""
        self.webhook_url = webhook_url

    def send_message(self, content: str, mentioned_list: Optional[list] = None) -> bool:
        """
        Send text message to WeChat webhook.

        Args:
            content: Message text
            mentioned_list: List of userids to mention (e.g., ['@all'])

        Returns:
            True if sent successfully
        """
        if not self.webhook_url:
            logger.warning("No WeChat webhook URL configured")
            return False

        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or []
            }
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get("errcode") == 0:
                logger.info(f"WeChat message sent: {content[:100]}...")
                return True
            else:
                logger.error(f"WeChat API error: {result}")
                return False
        except Exception as e:
            logger.error(f"Failed to send WeChat message: {e}")
            return False

    def send_markdown(self, content: str) -> bool:
        """Send markdown message to WeChat."""
        if not self.webhook_url:
            logger.warning("No WeChat webhook URL configured")
            return False

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get("errcode") == 0:
                logger.info(f"WeChat markdown sent: {content[:100]}...")
                return True
            else:
                logger.error(f"WeChat API error: {result}")
                return False
        except Exception as e:
            logger.error(f"Failed to send WeChat markdown: {e}")
            return False

    def send_scan_summary(
        self,
        scan_date: str,
        market_sentiment: str,
        top_opportunities: list,
        report_url: Optional[str] = None
    ) -> bool:
        """Send scan summary in markdown format."""
        # Build markdown content
        emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "watch": "🟡"}
        sentiment_emoji = emoji.get(market_sentiment.lower(), "⚪")

        content = f"""## {sentiment_emoji} 每日扫描完成 - {scan_date}

**市场情绪:** {market_sentiment.upper()}

### 🎯 Top 机会
"""

        for i, opp in enumerate(top_opportunities[:5], 1):
            content += f"{i}. **{opp.symbol}** ({opp.strategy}) - 置信度 {opp.confidence}%\n"
            content += f"   - 入场: ${opp.entry_price:.2f} | 止损: ${opp.stop_loss:.2f}\n"

        content += f"\n---\n共发现 {len(top_opportunities)} 个交易机会"

        if report_url:
            content += f"\n\n[📄 查看完整报告]({report_url})"

        return self.send_markdown(content)


class MultiNotifier:
    """Send notifications to multiple channels."""

    def __init__(
        self,
        discord_webhook: Optional[str] = None,
        wechat_webhook: Optional[str] = None
    ):
        """Initialize with multiple webhook URLs."""
        self.discord = DiscordNotifier(discord_webhook)
        self.wechat = WeChatNotifier(wechat_webhook)

    def send_scan_summary(
        self,
        scan_date: str,
        market_sentiment: str,
        top_opportunities: list,
        report_url: Optional[str] = None
    ) -> dict:
        """Send scan summary to all configured channels."""
        results = {}

        # Send to Discord
        results['discord'] = self.discord.send_scan_summary(
            scan_date, market_sentiment, top_opportunities, report_url
        )

        # Send to WeChat
        results['wechat'] = self.wechat.send_scan_summary(
            scan_date, market_sentiment, top_opportunities, report_url
        )

        return results
