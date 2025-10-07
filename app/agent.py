from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.utils.logger import logger

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import Tool, StructuredTool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from pydantic import BaseModel, Field

from app.utils.config import settings
from app.tools.earthquake_tool import fetch_recent_earthquakes
from app.tools.portfolio_tool import compute_portfolio_exposure
from app.tools.news_tool import fetch_live_news
from app.tools.alerts_tool import fetch_active_alerts

# Ensure OpenAI key is available and avoid base URL overrides that redirect traffic
OPENAI_API_KEY = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
# Prevent accidental reroute to non-OpenAI endpoints
for _k in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
    if os.environ.get(_k):
        os.environ.pop(_k, None)


# Structured tool schemas & functions
class EarthquakeInput(BaseModel):
    min_magnitude: float = Field(default=4.5, description="Minimum magnitude threshold")
    window: str = Field(default="day", description="Time window: hour|day|week|month")


def earthquake_tool_run(min_magnitude: float = 4.5, window: str = "day") -> str:
    result = fetch_recent_earthquakes(min_magnitude=min_magnitude, window=window, region_bbox=None)
    return json.dumps(result)


class PortfolioInput(BaseModel):
    portfolio_csv: Optional[str] = Field(default=None, description="Path to portfolio CSV; defaults to env setting")
    cone_feature: Dict[str, Any] = Field(description="GeoJSON Feature for forecast cone")


def portfolio_tool_run(portfolio_csv: Optional[str] = None, cone_feature: Dict[str, Any] = None) -> str:  # type: ignore[assignment]
    if cone_feature is None:
        raise ValueError("cone_feature missing")
    csv_path = portfolio_csv or settings.portfolio_csv
    result = compute_portfolio_exposure(csv_path, cone_feature)
    return json.dumps(result)


class NewsInput(BaseModel):
    query_terms: List[str] = Field(default_factory=list, description="Search keywords, e.g., ['flooding','power outage']")
    region_hint: Optional[str] = Field(default=None, description="Region hint, e.g., 'Florida'")
    page_size: int = Field(default=10, ge=1, le=50, description="Max articles to fetch")


def news_tool_run(query_terms: List[str], region_hint: Optional[str] = None, page_size: int = 10) -> str:
    result = fetch_live_news(query_terms, region_hint, page_size)
    return json.dumps(result)


def build_agent():
    tools = [
        StructuredTool.from_function(
            name="Earthquake_Data_Tool",
            description=(
                "Fetch recent USGS earthquakes and produce a union hazard polygon by buffering epicenters by magnitude. "
                "Args: min_magnitude (float, default 4.5), window ('hour'|'day'|'week'|'month'). "
                "Returns: fetched_at, source_title, source_url, feature_union, features"
            ),
            func=earthquake_tool_run,
            args_schema=EarthquakeInput,
        ),
        StructuredTool.from_function(
            name="Portfolio_Exposure_Tool",
            description=(
                "Compute exposed assets and TIV given a portfolio CSV and a hazard Feature. "
                "Args: portfolio_csv (optional), cone_feature (required)."
            ),
            func=portfolio_tool_run,
            args_schema=PortfolioInput,
        ),
        StructuredTool.from_function(
            name="Live_News_Tool",
            description=(
                "Query live headlines and parse article text for situational context. "
                "Args: query_terms (list), region_hint (optional), page_size (int)."
            ),
            func=news_tool_run,
            args_schema=NewsInput,
        ),
    ]

    system_prompt = (
        "You are LEEA, an autonomous risk intelligence agent for insurers. "
        "Your goal is to monitor impactful earthquakes and assess exposure for the specified portfolio. "
        "ALWAYS follow this plan: \n"
        "1) Call Earthquake_Data_Tool to get the latest hazard union for significant quakes.\n"
        "2) Call Portfolio_Exposure_Tool with the hazard union to compute exposure.\n"
        "3) Call Live_News_Tool with terms like earthquake, aftershock, damage, power outage, and the region.\n"
        "4) Synthesize a concise Markdown briefing with sections: Event Status, Exposure, Intelligence, Assessment, Next Actions.\n"
        "Use numbers with appropriate units and include links to sources. Keep output under 600 words."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", (
            "Initial Directive: Monitor earthquakes for impact on {region} using portfolio {portfolio_csv}.\n"
            "Use min magnitude 4.5 and window 'day' unless instructed otherwise."
        )),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature,
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools)
    return executor


def run_cycle() -> dict[str, Any]:
    executor = build_agent()
    input_vars = {
        "region": settings.monitor_region,
        "portfolio_csv": settings.portfolio_csv,
    }

    logger.info(
        "Starting LEEA agent cycle for region={region}",
        region=settings.monitor_region,
    )

    try:
        result = executor.invoke(input_vars)
        output_text = result.get("output") or ""
        status = "ok"
    except Exception:
        # Deterministic fallback chain: Earthquakes -> NWS Alerts -> News-only
        logger.debug("Agent failure; attempting Earthquakes -> Alerts -> News fallback chain")
        # 1) Earthquake deterministic
        try:
            eq = fetch_recent_earthquakes(min_magnitude=4.5, window="day", region_bbox=None)
            union = eq.get("feature_union")
            if union:
                exposure = compute_portfolio_exposure(settings.portfolio_csv, union)
                exp = exposure.get("exposure", {})
                lines = []
                lines.append("# LEEA Briefing (Earthquakes)")
                lines.append("")
                lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
                lines.append("")
                lines.append("## Event Status")
                lines.append(f"{eq.get('source_title')} | Events: {eq.get('count', 0)}")
                lines.append("")
                lines.append("## Exposure")
                lines.append(
                    f"Exposed assets: {exp.get('asset_count_exposed', 0)}/{exp.get('asset_count_total', 0)} | "
                    f"Exposed TIV: ${exp.get('total_insured_value_exposed', 0):,.0f} of ${exp.get('total_insured_value_total', 0):,.0f} "
                    f"(ratio {exp.get('exposure_ratio', 0):.2%})"
                )
                top = exp.get("top_exposed") or []
                if top:
                    lines.append("")
                    lines.append("Top exposed (by TIV):")
                    for r in top[:5]:
                        lines.append(f"- {r['PropertyID']} (${r['TotalInsuredValue']:,.0f}) @ ({r['Latitude']:.3f}, {r['Longitude']:.3f})")
                lines.append("")
                lines.append("## Intelligence")
                feats = eq.get("features") or []
                for f in feats[:5]:
                    p = f.get("properties", {})
                    place = p.get("place") or "Unknown"
                    mag = p.get("mag")
                    time_ms = p.get("time")
                    url = p.get("url") or ""
                    mag_s = f"M{mag}" if mag is not None else "M?"
                    bullet = f"- [{mag_s} — {place}]({url})" if url else f"- {mag_s} — {place}"
                    lines.append(bullet)
                lines.append("")
                lines.append("## Next Actions")
                lines.append("- Monitor USGS for aftershocks and updates; re-run exposure if hazard changes.")
                lines.append("- If exposure is material, prepare notifications to stakeholders.")
                output_text = "\n".join(lines)
                status = "ok_eq"
            else:
                raise RuntimeError("eq_no_union")
        except Exception:
            # 2) NWS Alerts fallback
            try:
                area = None
                if settings.monitor_region and isinstance(settings.monitor_region, str) and len(settings.monitor_region.strip()) == 2:
                    area = settings.monitor_region.strip().upper()
                alerts = fetch_active_alerts(event=None, area=area)
                union = alerts.get("feature_union")
                if union:
                    exposure = compute_portfolio_exposure(settings.portfolio_csv, union)
                    exp = exposure.get("exposure", {})
                    lines = []
                    lines.append("# LEEA Briefing (NWS Alerts)")
                    lines.append("")
                    lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
                    lines.append("")
                    lines.append("## Event Status")
                    lines.append(f"Active NWS alerts: {alerts.get('count', 0)} | Events: {', '.join(alerts.get('feature_union', {}).get('properties', {}).get('events', []) or [])}")
                    if area:
                        lines.append(f"Area filter: {area}")
                    lines.append("")
                    lines.append("## Exposure")
                    lines.append(
                        f"Exposed assets: {exp.get('asset_count_exposed', 0)}/{exp.get('asset_count_total', 0)} | "
                        f"Exposed TIV: ${exp.get('total_insured_value_exposed', 0):,.0f} of ${exp.get('total_insured_value_total', 0):,.0f} "
                        f"(ratio {exp.get('exposure_ratio', 0):.2%})"
                    )
                    lines.append("")
                    lines.append("## Next Actions")
                    lines.append("- Monitor NWS alerts for changes; re-run exposure if polygons update.")
                    output_text = "\n".join(lines)
                    status = "ok_alerts"
                else:
                    raise RuntimeError("alerts_no_geometry")
            except Exception:
                # 3) News-only fallback
                try:
                    news = fetch_live_news(query_terms=["earthquake", "aftershock", "damage", "power outage"], region_hint=(settings.monitor_region or None), page_size=10)
                except Exception:
                    news = {"articles": []}
                lines = []
                lines.append("# LEEA Briefing (news-only)")
                lines.append("")
                lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
                lines.append("")
                lines.append("## Event Status")
                lines.append("Autonomous agent failed; showing recent coverage relevant to earthquakes.")
                lines.append("")
                lines.append("## Intelligence (recent coverage)")
                if news.get("articles"):
                    for a in news["articles"][:10]:
                        title = a.get("title") or a.get("parsed", {}).get("title") or "Untitled"
                        url = a.get("url") or ""
                        source = (a.get("source") or "?")
                        pub = a.get("publishedAt") or a.get("parsed", {}).get("publish_date") or ""
                        bullet = f"- [{title}]({url}) — {source} {pub}" if url else f"- {title} — {source} {pub}"
                        lines.append(bullet)
                else:
                    lines.append("- No articles returned from NewsAPI.")
                lines.append("")
                lines.append("## Next Actions")
                lines.append("- Verify API keys and try again.")
                output_text = "\n".join(lines)
                status = "ok_news"

    # Persist briefing
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(settings.output_dir, "briefings")
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"briefing_{status}_{ts}.md"
    out_path = os.path.join(out_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_text)
    logger.info("Briefing written: {p}", p=out_path)

    return {"output_path": out_path, "text": output_text, "status": status}


def schedule() -> None:
    if settings.run_once:
        run_cycle()
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_cycle, trigger=IntervalTrigger(minutes=settings.run_interval_minutes), id="leea-cycle", max_instances=1, coalesce=True)
    scheduler.start()
    logger.info("Scheduler started: every {m} minutes", m=settings.run_interval_minutes)

    try:
        import time
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    schedule()
