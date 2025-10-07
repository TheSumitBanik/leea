from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from app.utils.http import http_client


NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"


def _build_params(event: Optional[str], area: Optional[str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "status": "actual",
        "limit": 200,
    }
    if event:
        params["event"] = event
    if area and len(area) == 2:
        params["area"] = area.upper()
    return params


def _union_features(features: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    geoms = []
    props_list = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            geoms.append(shape(geom))
            props_list.append(f.get("properties", {}))
        except Exception:
            continue
    if not geoms:
        return None
    merged = unary_union(geoms)
    # Basic summarised properties
    p = {
        "source": "NWS Alerts",
        "merged_count": len(geoms),
        "events": list({p.get("event") for p in props_list if p.get("event")}),
        "severities": list({p.get("severity") for p in props_list if p.get("severity")}),
    }
    return {
        "type": "Feature",
        "geometry": mapping(merged),
        "properties": p,
    }


def fetch_active_alerts(event: Optional[str] = None, area: Optional[str] = None) -> Dict[str, Any]:
    params = _build_params(event, area)
    data = http_client.get_json(NWS_ALERTS_URL, params=params, headers={"Accept": "application/geo+json"})
    features = data.get("features") or []
    union_feature = _union_features(features) if features else None
    out: Dict[str, Any] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_title": "NWS Active Alerts",
        "source_url": NWS_ALERTS_URL,
        "query": {k: v for k, v in params.items() if k in ("event", "area", "status", "limit")},
        "count": len(features),
        "feature_union": union_feature,
        "features": features[:50],  # cap to keep payload reasonable
    }
    return out
