#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of nlcd/raw.

    nlcd/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

PRODUCTS = {"LndCov": "Land cover", "FctImp": "Fractional impervious surface"}


def product(path: Path) -> dict:
    """Title an asset from its file name, Annual_NLCD_<product>_<year>_CU_C1V1.zip."""
    _, _, name, year, *_ = path.stem.split("_")
    return {"title": f"{PRODUCTS[name]} {year}"}


if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="nlcd-raw",
        title="Annual NLCD Collection 1.1 (raw)",
        description="USGS Annual National Land Cover Database Collection 1.1 data bundles as downloaded "
                    "by `_shared/scripts/download_raw.sh nlcd` from mrlc.gov: land cover (LndCov) and "
                    "fractional impervious surface (FctImp), one zip per product and year, 1985-2024. "
                    "Each zip holds one CONUS GeoTIFF (uint8, 30 m, 160000 x 105000, Albers Equal Area "
                    "on WGS 84, nodata 250) and its FGDC metadata. The other four Annual NLCD products "
                    "(land cover change, land cover confidence, impervious descriptor, spectral change "
                    "day of year) follow the same URL pattern and are not mirrored. Read-only.",
        bbox=[-129.28, 21.81, -63.12, 52.92],
        interval=("1985-01-01", "2024-12-31"),
        license_url="https://www.mrlc.gov/data",
        license_title="MRLC data",
        asset_fields=product,
        keywords=["land cover", "NLCD", "impervious surface", "land use", "Landsat"],
        providers=[pystac.Provider("U.S. Geological Survey", url="https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database",
                                   roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR]),
                   pystac.Provider("Multi-Resolution Land Characteristics Consortium", url="https://www.mrlc.gov",
                                   roles=[pystac.ProviderRole.HOST])],
    )
    save(SOURCE, raw)
