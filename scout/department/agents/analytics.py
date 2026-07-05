from __future__ import annotations

import logging
from datetime import datetime

from scout.config import get_settings
from scout.department.base_agent import BaseAgent
from scout.department.models import DailyReportRecord, KpiSnapshot
from scout.storage import db as scout_db
from scout.storage import department_db as db

logger = logging.getLogger(__name__)


class AnalyticsAgent(BaseAgent):
    agent_name = "analytics"

    async def generate_daily_report(self) -> DailyReportRecord:
        settings = get_settings()
        counts = await db.count_leads_period(days=1)
        deal_stats = await db.count_deals_by_status()
        dash = await scout_db.get_dashboard_stats()

        leads = counts["targets"]
        deals_won = deal_stats.get("won", 0)
        deals_new = deal_stats.get("new", 0) + deal_stats.get("in_progress", 0)
        ad_spend = settings.monthly_ad_budget_rub / 30.0
        revenue = settings.monthly_revenue_rub / 30.0
        llm_cost = dash.total_llm_cost_rub

        cpl = ad_spend / leads if leads > 0 and ad_spend > 0 else 0.0
        conversion = deals_won / leads if leads > 0 else 0.0
        cac = (llm_cost + ad_spend) / deals_won if deals_won > 0 else 0.0
        romi = revenue / (llm_cost + ad_spend) if (llm_cost + ad_spend) > 0 else 0.0

        kpi = KpiSnapshot(
            leads=leads,
            targets=counts["targets"],
            emails_sent=counts["sent"],
            deals_new=deals_new,
            deals_won=deals_won,
            conversion_rate=round(conversion, 4),
            cpl=round(cpl, 2),
            cac=round(cac, 2),
            romi=round(romi, 2),
            llm_cost_rub=llm_cost,
            ad_spend_rub=ad_spend,
            revenue_rub=revenue,
        )

        prompt = (
            f"Ежедневные KPI:\n"
            f"Лиды (target): {kpi.targets}\n"
            f"Отправлено email: {kpi.emails_sent}\n"
            f"Сделки new/in_progress: {kpi.deals_new}\n"
            f"Сделки won: {kpi.deals_won}\n"
            f"Конверсия: {kpi.conversion_rate:.1%}\n"
            f"CPL: {kpi.cpl} ₽\n"
            f"CAC: {kpi.cac} ₽\n"
            f"ROMI: {kpi.romi:.2f}\n"
            f"LLM cost: {kpi.llm_cost_rub:.2f} ₽\n\n"
            f"Дай summary и 3-5 конкретных рекомендаций для CMO."
        )
        result, summary, _ = await self.run(prompt, action="daily_report")
        recommendations = result.get("recommendations", [])
        if not recommendations and result.get("insights"):
            recommendations = result["insights"]

        report = DailyReportRecord(
            report_date=datetime.utcnow().strftime("%Y-%m-%d"),
            kpi=kpi,
            recommendations=recommendations,
            summary=result.get("summary", summary),
            raw_json=result,
        )
        return await db.save_daily_report(report)

    def format_telegram_digest(self, report: DailyReportRecord) -> str:
        k = report.kpi
        lines = [
            "📊 AI Marketing — ежедневный отчёт",
            f"Дата: {report.report_date}",
            "",
            f"Лиды: {k.targets} | Email: {k.emails_sent}",
            f"Сделки: +{k.deals_new} / won {k.deals_won}",
            f"Конверсия: {k.conversion_rate:.1%}",
            f"CPL: {k.cpl:.0f} ₽ | CAC: {k.cac:.0f} ₽ | ROMI: {k.romi:.2f}",
            f"LLM: {k.llm_cost_rub:.2f} ₽",
            "",
            report.summary[:400] if report.summary else "",
        ]
        if report.recommendations:
            lines.append("")
            lines.append("Рекомендации:")
            for i, rec in enumerate(report.recommendations[:5], 1):
                lines.append(f"{i}. {rec[:120]}")
        return "\n".join(lines)
