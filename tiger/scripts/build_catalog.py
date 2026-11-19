#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of tiger/raw.

    tiger/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

LAYERS = {
    "state": "States and equivalents", "county": "Counties and equivalents", "tract": "Census tracts",
    "bg": "Block groups", "place": "Places", "zcta520": "2020 ZIP Code Tabulation Areas",
    "aiannh": "American Indian / Alaska Native / Native Hawaiian areas", "uac20": "2020 urban areas",
    "cbsa": "Core based statistical areas", "primaryroads": "Primary roads",
    "prisecroads": "Primary and secondary roads", "rails": "Railroads",
}


def layer(path: Path) -> dict:
    """Title an asset from its file name, tl_2026_<us or state FIPS>_<layer>.zip."""
    _, _, area, name = path.stem.split("_")
    return {"title": LAYERS[name] + ("" if area == "us" else f", state FIPS {area}")}


if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="tiger-raw",
        title="Census TIGER/Line 2026 (raw)",
        description="Census Bureau TIGER/Line 2026 shapefile zips as downloaded by "
                    "`_shared/scripts/download_raw.sh tiger` from the URLs in `scripts/urls.txt`: "
                    + ", ".join(LAYERS) + ". National layers are one zip (`tl_2026_us_<layer>.zip`); "
                    "tract, bg, place and prisecroads are one zip per state or territory "
                    "(`tl_2026_<FIPS>_<layer>.zip`). Geometries are EPSG:4269 (NAD83). Boundaries "
                    "are as of January 1, 2026. Read-only.",
        bbox=[-180.0, -14.6, 180.0, 71.4],
        interval=("2026-01-01", "2026-01-01"),
        license_url="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        license_title="TIGER/Line Shapefiles",
        asset_fields=layer,
        keywords=["boundaries", "census", "TIGER", "counties", "tracts", "roads"],
        providers=[pystac.Provider("U.S. Census Bureau", url="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
                                   roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                                          pystac.ProviderRole.HOST])],
    )
    save(SOURCE, raw)
