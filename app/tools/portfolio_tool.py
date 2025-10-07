from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Tuple

import pandas as pd
from shapely.geometry import Point, shape
from shapely.prepared import prep

from app.utils.logger import logger


@dataclass
class ExposureSummary:
    portfolio_path: str
    asset_count_total: int
    asset_count_exposed: int
    total_insured_value_total: float
    total_insured_value_exposed: float
    exposure_ratio: float
    bounds: Tuple[float, float, float, float] | None
    top_exposed: list[dict]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("bounds") is not None:
            b = d["bounds"]
            d["bounds"] = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        return d


def _compute_bounds(latitudes: Iterable[float], longitudes: Iterable[float]) -> Tuple[float, float, float, float] | None:
    lats = list(latitudes)
    lons = list(longitudes)
    if not lats or not lons:
        return None
    return (float(min(lons)), float(min(lats)), float(max(lons)), float(max(lats)))


def compute_portfolio_exposure(portfolio_csv: str, cone_feature_json: Any) -> dict:
    """
    Compute exposure of portfolio assets (points) against the provided cone polygon feature.
    cone_feature_json can be a dict Feature or a JSON string. Returns a summary dict.
    """
    logger.info(f"Loading portfolio: {portfolio_csv}")
    df = pd.read_csv(portfolio_csv)

    required = {"PropertyID", "Latitude", "Longitude", "TotalInsuredValue"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Portfolio CSV missing columns: {missing}")

    # Coerce numeric
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df["TotalInsuredValue"] = pd.to_numeric(df["TotalInsuredValue"], errors="coerce").fillna(0.0)

    # Drop rows with invalid coords
    df = df.dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)

    # Parse cone feature
    if isinstance(cone_feature_json, str):
        cone_feature = json.loads(cone_feature_json)
    else:
        cone_feature = cone_feature_json
    poly = shape(cone_feature["geometry"])  # shapely geometry
    prepared_poly = prep(poly)

    # Determine exposure via point-in-polygon test
    exposed_flags = []
    for _, row in df.iterrows():
        pt = Point(float(row["Longitude"]), float(row["Latitude"]))
        exposed_flags.append(prepared_poly.intersects(pt))
    df["Exposed"] = exposed_flags

    tiv_total = float(df["TotalInsuredValue"].sum())
    exposed_df = df[df["Exposed"]]
    tiv_exposed = float(exposed_df["TotalInsuredValue"].sum())

    # Top exposed
    top = exposed_df.sort_values("TotalInsuredValue", ascending=False).head(10)
    top_records: list[dict] = []
    for _, r in top.iterrows():
        top_records.append(
            {
                "PropertyID": r["PropertyID"],
                "Latitude": float(r["Latitude"]),
                "Longitude": float(r["Longitude"]),
                "TotalInsuredValue": float(r["TotalInsuredValue"]),
            }
        )

    bounds = _compute_bounds(exposed_df["Latitude"].tolist(), exposed_df["Longitude"].tolist()) if not exposed_df.empty else None

    summary = ExposureSummary(
        portfolio_path=portfolio_csv,
        asset_count_total=int(len(df)),
        asset_count_exposed=int(len(exposed_df)),
        total_insured_value_total=tiv_total,
        total_insured_value_exposed=tiv_exposed,
        exposure_ratio=(tiv_exposed / tiv_total) if tiv_total > 0 else 0.0,
        bounds=bounds,
        top_exposed=top_records,
    )

    out = {
        "computed_at": datetime.utcnow().isoformat() + "Z",
        "exposure": summary.to_dict(),
    }
    logger.info(
        "Exposure: {exposed}/{total} assets; ${tiv_exposed:,.0f} exposed of ${tiv_total:,.0f}",
        exposed=summary.asset_count_exposed,
        total=summary.asset_count_total,
        tiv_exposed=summary.total_insured_value_exposed,
        tiv_total=summary.total_insured_value_total,
    )
    return out
