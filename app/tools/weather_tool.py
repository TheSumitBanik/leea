from __future__ import annotations
import json
import os
import tempfile
import zipfile
from datetime import datetime
from typing import Optional, List, Dict, Any

from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely.geometry as sgeom
import shapefile  # pyshp

from app.utils.http import http_client
from app.utils.logger import logger

NHC_GIS_FEEDS = [
    "https://www.nhc.noaa.gov/gis-at.xml",  # Atlantic basin
    "https://www.nhc.noaa.gov/gis-ep.xml",  # Eastern Pacific basin
]


def _parse_gis_feed_for_cone_links(target_name: Optional[str] = None) -> List[Dict[str, str]]:
    """Return a list of candidate cone products from NHC feeds with type in {geojson, shpzip}."""
    items: List[Dict[str, str]] = []
    for feed_url in NHC_GIS_FEEDS:
        try:
            feed = http_client.get_feed(feed_url)
        except Exception as e:
            logger.warning(f"Failed to fetch NHC GIS feed {feed_url}: {e}")
            continue
        for entry in feed.entries:
            title = str(entry.get("title", ""))
            if "cone" not in title.lower():
                continue
            links = entry.get("links") or []
            for l in links:
                href = l.get("href") if isinstance(l, dict) else None
                if not href:
                    continue
                href_s = str(href)
                lower = href_s.lower()
                if lower.endswith(".geojson") or "geojson" in lower:
                    items.append({"title": title, "url": href_s, "type": "geojson"})
                elif lower.endswith(".zip") and ("cone" in lower or "5day" in lower):
                    items.append({"title": title, "url": href_s, "type": "shpzip"})
    logger.debug(f"NHC cone candidates found: {len(items)}")
    return items


def _load_cone_geojson(url: str) -> Dict[str, Any]:
    logger.info(f"Loading cone GeoJSON: {url}")
    data = http_client.get_json(url)
    features = data.get("features", [])
    geoms = [shape(f.get("geometry")) for f in features if f.get("geometry")]
    if not geoms:
        raise ValueError("No geometries found in cone GeoJSON")
    union = unary_union(geoms)
    return mapping(union)


def _load_cone_shapefile_zip(url: str) -> Dict[str, Any]:
    """Download shapefile ZIP and union all polygon features using pure Python (pyshp + shapely)."""
    logger.info(f"Loading cone shapefile ZIP: {url}")
    resp = http_client.session.get(url, timeout=60)
    resp.raise_for_status()

    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "cone.zip")
        with open(zip_path, "wb") as f:
            f.write(resp.content)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(td)
        # Find the .shp file
        shp_files = [p for p in os.listdir(td) if p.lower().endswith(".shp")]
        if not shp_files:
            raise ValueError("No .shp file found in ZIP")
        shp_path = os.path.join(td, shp_files[0])
        r = shapefile.Reader(shp_path)
        geoms: List[Polygon | MultiPolygon] = []
        for s in r.shapes():
            # Convert pyshp geometry to shapely
            if s.shapeType not in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
                continue
            parts = list(s.parts) + [len(s.points)]
            rings = []
            for i in range(len(parts) - 1):
                ring = s.points[parts[i]:parts[i+1]]
                if len(ring) >= 3:
                    rings.append(ring)
            if not rings:
                continue
            exterior = rings[0]
            interiors = rings[1:] if len(rings) > 1 else []
            poly = sgeom.Polygon(exterior, interiors)
            if not poly.is_empty:
                geoms.append(poly)
        if not geoms:
            raise ValueError("No polygon geometries in shapefile")
        union = unary_union(geoms)
        return mapping(union)


def fetch_current_cone(target_name: Optional[str] = None) -> dict:
    """
    Fetch the latest forecast cone geometry for active storms from NHC GIS feeds.
    Prefer GeoJSON; fall back to shapefile ZIP if needed. If target_name is empty, pick the first available.
    """
    items = _parse_gis_feed_for_cone_links(target_name)
    if not items:
        raise RuntimeError("No cone products found in NHC GIS feeds")

    chosen = None
    if target_name:
        for it in items:
            if target_name.lower().split()[0] in it["title"].lower():
                chosen = it
                break
    if not chosen:
        # Prefer geojson first when available
        geo = [it for it in items if it["type"] == "geojson"]
        chosen = geo[0] if geo else items[0]

    if chosen["type"] == "geojson":
        geom = _load_cone_geojson(chosen["url"])
    else:
        geom = _load_cone_shapefile_zip(chosen["url"])

    feature = {
        "type": "Feature",
        "properties": {
            "source": chosen["url"],
            "title": chosen["title"],
        },
        "geometry": geom,
    }

    return {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "source_title": chosen["title"],
        "source_url": chosen["url"],
        "feature": feature,
    }
