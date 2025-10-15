# LEEA — Lightweight Earthquake Exposure Agent

## Overview

LEEA is a small tool-augmented risk intelligence agent. 

The current project scope is earthquake-first: USGS earthquake feeds are the primary hazard source. When USGS geometry is present the agent buffers epicenters by magnitude, unions them into a hazard polygon, computes portfolio exposure, and emits a Markdown briefing. Deterministic fallbacks are NWS active alerts (polygons) and a news-only briefing (NewsAPI).

What it demonstrates

- Real-time data ingestion from USGS (always-active feeds).
- Geospatial processing: buffering epicenters by magnitude and unioning into hazard polygons (Shapely).
- Exposure analytics on a CSV portfolio: exposed asset counts, TIV, exposure ratio, and top exposed assets.
- Tool-augmented GenAI design: LLM-driven planning + deterministic fallbacks for robustness.
- Observability: HTTP previews (truncated, with masked secrets) in logs for auditing live calls.

Repository layout (important files)

- app/agent.py — main agent orchestration and fallback chain (USGS → NWS → News).
- app/tools/earthquake_tool.py — USGS feed ingestion and hazard polygon creation.
- app/tools/alerts_tool.py — NWS active alerts ingestion and unioning for fallback.
- app/tools/news_tool.py — NewsAPI integration used for deterministic briefings.
- app/tools/portfolio_tool.py — computes portfolio exposure against a hazard feature.
- app/utils/http.py — HTTP client with safe logging and retries.
- data/portfolio_alpha.csv — sample portfolio (small) for quick demos.
- output/briefings — generated Markdown briefings.
- output/logs/leea.log — runtime logs and HTTP previews.

Quick start (macOS)

1) Create and activate a virtualenv (recommended):
   - python3 -m venv .venv && source .venv/bin/activate
   - pip install -r requirements.txt

2) Create a .env file in the project root with at least:
   - PORTFOLIO_CSV=data/portfolio_alpha.csv
   - OUTPUT_DIR=output
   - RUN_ONCE=1          # run a single cycle for demo

   Optional (recommended):
   - NEWSAPI_KEY=<your NewsAPI key>
   - OPENAI_API_KEY=<your OpenAI key>  # for LLM synthesis (using model from nvidia nim)
   - MONITOR_REGION=CA  # optional 2-letter state code to scope NWS alerts

3) Run one cycle for the demo:
   - RUN_ONCE=1 python -m app.agent

4) Inspect results:
   - Briefings: output/briefings/*.md
   - Logs (HTTP previews + run info): output/logs/leea.log
