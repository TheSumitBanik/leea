from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from shapely.geometry import Point, shape, mapping
from shapely.ops import unary_union

from app.utils.http import http_client

USGS_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"


def _feed_for(min_magnitude: float, window: str) -> Tuple[str, str]:
    # Map min magnitude to USGS feed name
    # windows: 'hour' | 'day' | 'week' | 'month'
    win = window if window in ("hour", "day", "week", "month") else "day"
    if min_magnitude >= 7.0:
        name = f"significant_{win}.geojson"
        label = f"USGS Significant Earthquakes ({win})"
    elif min_magnitude >= 4.5:
        name = f"4.5_{win}.geojson"
        label = f"USGS M4.5+ Earthquakes ({win})"
    elif min_magnitude >= 2.5:
        name = f"2.5_{win}.geojson"
        label = f"USGS M2.5+ Earthquakes ({win})"
    else:
        name = f"all_{win}.geojson"
        label = f"USGS All Earthquakes ({win})"
    return f"{USGS_BASE}/{name}", label


def _buffer_km_for_mag(m: float) -> float:
    # Simple demo mapping of magnitude to buffer radius (km)
    if m >= 7.0:
        return 200.0
    if m >= 6.0:
        return 125.0
    if m >= 5.0:
        return 75.0
    if m >= 4.0:
        return 50.0
    return 25.0


def _filter_bbox(features: List[Dict[str, Any]], bbox: List[float]) -> List[Dict[str, Any]]:
    minx, miny, maxx, maxy = bbox
    out: List[Dict[str, Any]] = []
    for f in features:
        geom = f.get("geometry")
        if not geom or geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if minx <= lon <= maxx and miny <= lat <= maxy:
            out.append(f)
    return out


def fetch_recent_earthquakes(min_magnitude: float = 4.5, window: str = "day", region_bbox: Optional[List[float]] = None) -> Dict[str, Any]:
    url, label = _feed_for(min_magnitude, window)
    data = http_client.get_json(url)
    feats: List[Dict[str, Any]] = data.get("features", [])
    if region_bbox and len(region_bbox) == 4:
        feats = _filter_bbox(feats, region_bbox)

    buffers = []
    for f in feats:
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        mag = 0.0
        try:
            mag = float((f.get("properties") or {}).get("mag") or 0.0)
        except Exception:
            mag = 0.0
        km = _buffer_km_for_mag(mag)
        deg = km / 111.0  # rough degrees-per-km at mid-latitudes
        buffers.append(Point(lon, lat).buffer(deg))

    union_feature = None
    if buffers:
        merged = unary_union(buffers)
        union_feature = {
            "type": "Feature",
            "geometry": mapping(merged),
            "properties": {
                "source": "USGS",
                "min_magnitude": min_magnitude,
                "window": window,
                "region_bbox": region_bbox,
                "count": len(buffers),
            },
        }

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_title": label,
        "source_url": url,
        "query": {"min_magnitude": min_magnitude, "window": window, "region_bbox": region_bbox},
        "count": len(feats),
        "feature_union": union_feature,
        "features": feats[:200],
    }
