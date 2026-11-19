#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of usgs-3dep/raw and the Catalog of usgs-3dep/derived.

    usgs-3dep/scripts/build_catalog.py
"""

import re
import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import FILE, PROJECTION, file_asset, raw_collection, save, utc  # noqa: E402

VRT = SOURCE / "derived/USGS_Seamless_DEM_13.vrt"
LICENSE = "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"
USGS = pystac.Provider("U.S. Geological Survey", url="https://www.usgs.gov/3d-elevation-program",
                       roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                              pystac.ProviderRole.HOST])
INTERVAL = (None, "2026-11-19")  # tile source dates vary; the end is the download date


def tile_bbox(path: Path) -> list[float] | None:
    """[west, south, east, north] of USGS_13_<n|s>YY<e|w>XXX.tif, named by its north-west corner."""
    m = re.fullmatch(r"USGS_13_([ns])(\d+)([ew])(\d+)", path.stem)
    if m is None:
        return None
    north = int(m[2]) * (1 if m[1] == "n" else -1)
    west = int(m[4]) * (1 if m[3] == "e" else -1)
    return [west, north - 1, west + 1, north]


def tile_fields(path: Path) -> dict:
    bbox = tile_bbox(path)
    return {"proj:code": "EPSG:4269", "proj:bbox": bbox} if bbox else {}


if __name__ == "__main__":
    boxes = [b for b in map(tile_bbox, (SOURCE / "raw").iterdir()) if b]
    # Tiles lie on both sides of the antimeridian, so the longitude range is the full circle.
    bbox = [-180.0, min(b[1] for b in boxes), 180.0, max(b[3] for b in boxes)]
    raw = raw_collection(
        SOURCE,
        id="usgs-3dep-raw",
        title="USGS 3DEP 1/3 arc-second DEM (raw)",
        description=f"USGS 3D Elevation Program seamless 1/3 arc-second (about 10 m) DEM: the {len(boxes)} "
                    "1 x 1 degree GeoTIFF tiles under `StagedProducts/Elevation/13/TIFF/current/` in the "
                    "USGS `prd-tnm` S3 bucket, as downloaded by `_shared/scripts/download_raw.sh "
                    "usgs-3dep`, plus the USGS VRT that mosaics them from S3. Covers CONUS, Hawaii, "
                    "the territories and the parts of Alaska with 1/3 arc-second data. Tiles are "
                    "float32 metres (NAVD88 in CONUS), EPSG:4269, 10812 x 10812 with a 6-pixel overlap, "
                    "nodata -999999, and are named by their north-west corner; each asset's `proj:bbox` "
                    "is the tile's nominal 1 x 1 degree cell. Source dates vary by tile. Read-only.",
        bbox=bbox,
        interval=INTERVAL,
        license_url=LICENSE,
        license_title="USGS copyrights and credits",
        asset_fields=tile_fields,
        stac_extensions=[PROJECTION],
        keywords=["elevation", "DEM", "3DEP", "terrain", "topography"],
        providers=[USGS],
    )
    derived = pystac.Catalog(
        id="usgs-3dep-derived",
        title="USGS 3DEP 1/3 arc-second DEM (derived)",
        description="Products built from `usgs-3dep/raw` by the code in `usgs-3dep/scripts`.",
    )
    mosaic = pystac.Collection(
        id="usgs-3dep-13-vrt",
        title="USGS 3DEP 1/3 arc-second DEM, seamless VRT",
        description="GDAL VRT that mosaics every tile in `usgs-3dep/raw` into one float32 raster in "
                    "EPSG:4269 (elevation in metres, nodata -999999). It is the USGS seamless VRT with "
                    "each tile's S3 URL replaced by the local file, written by "
                    "`usgs-3dep/scripts/build_vrt.sh`.",
        extent=pystac.Extent(pystac.SpatialExtent([bbox]),
                             pystac.TemporalExtent([[utc(INTERVAL[0]), utc(INTERVAL[1])]])),
        license="other",
        keywords=["elevation", "DEM", "3DEP", "terrain", "VRT"],
        providers=[USGS, pystac.Provider("cowy", roles=[pystac.ProviderRole.PROCESSOR, pystac.ProviderRole.HOST])],
        stac_extensions=[FILE, PROJECTION],
    )
    mosaic.add_link(pystac.Link("license", LICENSE, media_type="text/html", title="USGS copyrights and credits"))
    mosaic.add_asset("vrt", file_asset(VRT, **{"proj:code": "EPSG:4269"}))
    derived.add_child(mosaic)
    save(SOURCE, raw, derived, {mosaic: VRT.with_suffix(".json")})
