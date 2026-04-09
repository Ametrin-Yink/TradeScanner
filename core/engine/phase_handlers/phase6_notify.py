"""Phase 6: Push Notifications handler."""
import logging
from datetime import datetime

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.notifier import MultiNotifier
from config.settings import settings

logger = logging.getLogger(__name__)


class Phase6NotifyHandler(PhaseHandler):
    NAME = "phase6"
    DESCRIPTION = "Push Notifications"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 6: Push Notifications")
        logger.info("=" * 60)

        notifier = MultiNotifier(
            discord_webhook=settings.get_secret('discord.webhook_url'),
            wechat_webhook=settings.get_secret('wechat.webhook_url'),
        )

        report_filename = ctx.report_path.split('/')[-1]
        report_url = f"http://47.90.229.136:19801/reports/{report_filename}"

        scan_date = datetime.now().strftime('%Y-%m-%d')

        ai_confidence = ctx.regime_analysis.get('ai_confidence', 0)
        ai_reasoning = ctx.regime_analysis.get('ai_reasoning', '')

        logger.info(f"AI Regime Confidence: {ai_confidence}%")
        logger.info(f"AI Reasoning: {ai_reasoning[:100]}...")
        logger.info(f"Final candidates: {len(ctx.top_10)}")

        results = notifier.send_scan_summary(
            scan_date=scan_date,
            market_sentiment=ctx.regime,
            top_opportunities=ctx.top_10,
            report_url=report_url
        )

        logger.info(f"Discord: {'sent' if results.get('discord') else 'failed'}")
        logger.info(f"WeChat: {'sent' if results.get('wechat') else 'failed'}")

        return PhaseResult(success=True, data={})
