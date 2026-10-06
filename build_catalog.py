#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10", "pyproj>=3.6", "pyarrow>=17"]
# ///
"""Build the STAC catalog of /project/cowy/data/*/derived.

    ./build_catalog.py

The catalog files live beside the data they describe:

    catalog.json                              root Catalog
    <source>/catalog.json                     one Catalog per /project/cowy/data/<source>
    <source>/derived/<store>.json             one Collection per <source>/derived/<store>.{zarr,parquet}

A Zarr store's Collection has a single ``zarr`` asset and datacube (cube:*)
fields read from the store's consolidated metadata; variable descriptions come
from the LANDFIRE metadata XML inside each array's source zip in ``raw/``, when
that zip is present. A GeoParquet file's Collection has a single ``parquet``
asset and table (table:*) fields read from the Parquet footer; column
descriptions come from the FGDC metadata XML in a source zip.

All hrefs are relative, so the catalog resolves under both /project and
/cluster/medbow/project.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pystac
from pyproj import Transformer

DATA = Path(__file__).resolve().parent
LANDFIRE = DATA / "landfire"
STORE = LANDFIRE / "derived/lf2025_fuels_terrain.zarr"
STRUCTURES = DATA / "fema-usa-structures"
STRUCTURES_FILE = STRUCTURES / "derived/usa_structures.parquet"

DATACUBE = "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
PROJECTION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
XARRAY = "https://stac-extensions.github.io/xarray-assets/v1.0.0/schema.json"
TABLE = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"


#-----------------------------------------------------------------------------# Zarr metadata
def mtime(path: Path) -> str:
    """Modification time as an RFC 3339 string, for an asset's ``updated`` field."""
    return pystac.utils.datetime_to_str(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))


def read_store(path: Path) -> tuple[dict, dict[str, dict]]:
    """Root attributes and per-array metadata from a consolidated Zarr v3 store."""
    root = json.loads((path / "zarr.json").read_text())
    arrays = root.get("consolidated_metadata", {}).get("metadata")
    if arrays is None:
        raise SystemExit(f"{path} has no consolidated metadata; run zarr.consolidate_metadata")
    return root["attributes"], arrays


def landfire_title(zip_path: Path) -> str | None:
    """The <title> of the product's General_Metadata XML."""
    if not zip_path.exists():
        return None
    with zipfile.ZipFile(zip_path) as zf:
        xml = [n for n in zf.namelist() if "/General_Metadata/" in n and n.endswith(".xml")]
        if not xml:
            return None
        m = re.search(r"<title>(.*?)</title>", zf.read(xml[0]).decode("utf-8", "ignore"), re.S)
        return m.group(1).strip() if m else None


#-----------------------------------------------------------------------------# Collection
def landfire_collection(store: Path, metadata_from: Path, raw: Path) -> pystac.Collection:
    attrs, arrays = read_store(metadata_from)
    res, _, x0, _, _, y1 = attrs["transform"]
    ny, nx = arrays["y"]["shape"][0], arrays["x"]["shape"][0]
    native = (x0, y1 - ny * res, x0 + nx * res, y1)
    bbox = list(Transformer.from_crs(attrs["crs"], "EPSG:4326", always_xy=True)
                .transform_bounds(*native, densify_pts=101))
    years = sorted(int(r[2:]) for r in attrs["releases"])
    epsg = int(attrs["crs"].split(":")[1])

    data_vars = {k: v for k, v in arrays.items()
                 if v.get("attributes", {}).get("landfire_product") is not None}
    variables = {}
    for name, meta in sorted(data_vars.items()):
        a = meta["attributes"]
        variables[name] = {
            "dimensions": ["y", "x"],
            "type": "data",
            "description": landfire_title(raw / a["source_zip"]) or a["landfire_product"],
            "data_type": meta["data_type"],
            "landfire:product": a["landfire_product"],
            "landfire:release": a["landfire_release"],
        }
        # Zarr's fill_value defaults to 0 when the source has no nodata; trust only _FillValue
        if "_FillValue" in a:
            variables[name]["nodata"] = a["_FillValue"]

    collection = pystac.Collection(
        id=store.stem.replace("_", "-"),
        title="LANDFIRE LF2025 fuels + LF2020 terrain",
        description=(
            f"{len(data_vars)} LANDFIRE CONUS layers on one {res:g} m EPSG:{epsg} grid "
            f"({ny} x {nx}) in a single Zarr v3 store: the LF2025 fuel, vegetation and "
            "disturbance layers plus LF2020 terrain (Elev, SlpD, SlpP, Asp), which LANDFIRE "
            "does not reissue each release. Arrays are named by bare product code. "
            "LANDFIRE value-attribute tables are embedded in each array's `attribute_table` "
            "attribute. Built by `landfire/scripts/landfire_to_zarr.py`."
        ),
        extent=pystac.Extent(
            pystac.SpatialExtent([bbox]),
            pystac.TemporalExtent([[datetime(years[0], 1, 1, tzinfo=timezone.utc),
                                    datetime(years[-1], 12, 31, 23, 59, 59, tzinfo=timezone.utc)]]),
        ),
        license="other",
        keywords=["LANDFIRE", "fuels", "wildfire", "terrain", "CONUS", "zarr"],
        providers=[
            pystac.Provider("LANDFIRE", roles=[pystac.ProviderRole.PRODUCER,
                                               pystac.ProviderRole.LICENSOR],
                            url="https://landfire.gov"),
            pystac.Provider("cowy", roles=[pystac.ProviderRole.PROCESSOR,
                                           pystac.ProviderRole.HOST]),
        ],
        stac_extensions=[DATACUBE, PROJECTION, XARRAY],
        extra_fields={
            "cube:dimensions": {
                "x": {"type": "spatial", "axis": "x", "extent": [native[0], native[2]],
                      "step": res, "reference_system": epsg},
                "y": {"type": "spatial", "axis": "y", "extent": [native[1], native[3]],
                      "step": -res, "reference_system": epsg},
            },
            "cube:variables": variables,
        },
    )
    collection.add_link(pystac.Link("license", "https://landfire.gov/data/faq",
                                    media_type="text/html", title="LANDFIRE data use"))
    collection.add_asset("zarr", pystac.Asset(
        href=str(store),
        title=store.name,
        media_type="application/vnd.zarr; version=3",
        roles=["data", "zarr"],
        extra_fields={
            "proj:code": attrs["crs"],
            "proj:shape": [ny, nx],
            "proj:transform": attrs["transform"],
            "proj:bbox": list(native),
            "xarray:open_kwargs": {"engine": "zarr", "consolidated": True},
            "updated": mtime(metadata_from / "zarr.json"),
        },
    ))
    return collection


#-----------------------------------------------------------------------------# GeoParquet
NON_CONUS = {"Alaska", "Hawaii", "American Samoa", "Guam", "Northern Marianas",
             "Puerto Rico", "Virgin Islands"}


def fgdc_definitions(raw: Path) -> dict[str, str]:
    """attrlabl -> attrdef from the FGDC metadata XML in the newest zip in ``raw``."""
    newest = max(raw.glob("*.zip"), key=lambda p: p.stat().st_mtime, default=None)
    if newest is None:
        return {}
    with zipfile.ZipFile(newest) as zf:
        xml = [n for n in zf.namelist() if n.endswith("_metadata.xml")]
        if not xml:
            return {}
        root = ET.fromstring(zf.read(xml[0]))
    return {a.findtext("attrlabl"): " ".join(a.findtext("attrdef", "").split())
            for a in root.iter("attr")}


def region_bbox(path: Path, state: str) -> list[float]:
    """Exact bbox of one PROP_ST value; west > east when it crosses the antimeridian."""
    b = pq.read_table(path, columns=["bbox"], filters=[("PROP_ST", "=", state)])["bbox"].combine_chunks()
    xmin, xmax = b.field("xmin"), b.field("xmax")
    west, east = pc.min(xmin).as_py(), pc.max(xmax).as_py()
    if east - west > 180:
        west = pc.min(pc.filter(xmin, pc.greater_equal(xmin, 0))).as_py()
        east = pc.max(pc.filter(xmax, pc.less(xmax, 0))).as_py()
    return [west, pc.min(b.field("ymin")).as_py(), east, pc.max(b.field("ymax")).as_py()]


def structures_collection(path: Path, raw: Path) -> pystac.Collection:
    pf = pq.ParquetFile(path)
    md, schema = pf.metadata, pf.schema_arrow
    geo = json.loads(schema.metadata[b"geo"])
    geom = geo["primary_column"]

    # Per-row-group statistics give the extents without reading any rows.
    col = {md.row_group(0).column(j).path_in_schema: j for j in range(md.num_columns)}
    conus, t0, t1 = [180.0, 90.0, -180.0, -90.0], None, None
    for r in range(md.num_row_groups):
        stat = lambda name: md.row_group(r).column(col[name]).statistics
        if stat("PROP_ST").max not in NON_CONUS:
            conus = [min(conus[0], stat("bbox.xmin").min), min(conus[1], stat("bbox.ymin").min),
                     max(conus[2], stat("bbox.xmax").max), max(conus[3], stat("bbox.ymax").max)]
        d = stat("IMAGE_DATE")
        if d.has_min_max:
            t0 = d.min if t0 is None else min(t0, d.min)
            t1 = d.max if t1 is None else max(t1, d.max)
    _, ymin, _, ymax = geo["columns"][geom]["bbox"]  # Alaska crosses the antimeridian
    regions = [conus] + [region_bbox(path, s) for s in sorted(NON_CONUS)]

    defs = fgdc_definitions(raw)
    defs[geom] = "Building footprint, WKB-encoded."
    defs["bbox"] = "Footprint bounding box (GeoParquet 1.1 covering column) for bbox filtering."
    columns = [{"name": f.name, "type": str(f.type), **({"description": defs[f.name]} if f.name in defs else {})}
               for f in schema]

    collection = pystac.Collection(
        id=path.stem.replace("_", "-"),
        title="FEMA USA Structures",
        description=(
            f"{md.num_rows:,} building footprints (structures over 450 sq ft) for the 50 states, "
            "DC and five territories, from the FEMA/ORNL USA Structures state File Geodatabases "
            "in `fema-usa-structures/raw`, merged into one GeoParquet 1.1 file. Attributes include "
            "occupancy class, address, height, area, adjacent ground elevation and estimated "
            "population. Rows are Hilbert-sorted within each state and carry a `bbox` covering "
            "column, so bbox filters in DuckDB, GeoPandas and GDAL skip row groups outside the "
            "query. Built by `fema-usa-structures/scripts/build_geoparquet.py`."
        ),
        extent=pystac.Extent(
            pystac.SpatialExtent([[-180.0, ymin, 180.0, ymax], *regions]),
            pystac.TemporalExtent([[t0, t1]]),
        ),
        license="other",
        keywords=["buildings", "structures", "footprints", "FEMA", "exposure", "geoparquet"],
        providers=[
            pystac.Provider("Oak Ridge National Laboratory", roles=[pystac.ProviderRole.PRODUCER],
                            url="https://www.ornl.gov"),
            pystac.Provider("FEMA", roles=[pystac.ProviderRole.LICENSOR, pystac.ProviderRole.HOST],
                            url="https://gis-fema.hub.arcgis.com/pages/usa-structures"),
            pystac.Provider("cowy", roles=[pystac.ProviderRole.PROCESSOR,
                                           pystac.ProviderRole.HOST]),
        ],
        stac_extensions=[TABLE, PROJECTION, FILE],
        extra_fields={
            "table:columns": columns,
            "table:primary_geometry": geom,
            "table:row_count": md.num_rows,
        },
    )
    collection.add_link(pystac.Link("license", "https://gis-fema.hub.arcgis.com/pages/usa-structures",
                                    media_type="text/html", title="USA Structures"))
    collection.add_asset("parquet", pystac.Asset(
        href=str(path),
        title=path.name,
        media_type="application/vnd.apache.parquet",
        roles=["data"],
        extra_fields={"proj:code": "EPSG:4326", "file:size": path.stat().st_size,
                      "updated": mtime(path)},
    ))
    return collection


#-----------------------------------------------------------------------------# Main
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--metadata-from", type=Path, default=STORE,
                   help="read Zarr metadata from this copy of the store instead of the "
                        "published path (asset hrefs still point at the published path)")
    p.add_argument("--raw", type=Path, default=LANDFIRE / "raw",
                   help="LANDFIRE zips, for variable descriptions (default: landfire/raw)")
    args = p.parse_args(argv)

    catalog = pystac.Catalog(
        id="cowy-data",
        title="cowy shared data",
        description="Datasets in /project/cowy/data, one child Catalog per `<source>` "
                    "directory; see /project/cowy/data/README.md for layout and owners.",
    )
    landfire = pystac.Catalog(
        id="landfire",
        title="LANDFIRE",
        description="Products derived from LANDFIRE (https://landfire.gov) zips in "
                    "`landfire/raw`, built by the code in `landfire/scripts`. One Collection "
                    "per store in `landfire/derived`.",
    )
    fuels = landfire_collection(STORE, args.metadata_from, args.raw)
    landfire.add_child(fuels)
    catalog.add_child(landfire)

    fema = pystac.Catalog(
        id="fema-usa-structures",
        title="FEMA USA Structures",
        description="Products derived from the FEMA/ORNL USA Structures state zips in "
                    "`fema-usa-structures/raw`, built by the code in `fema-usa-structures/scripts`. "
                    "One Collection per file in `fema-usa-structures/derived`.",
    )
    structures = structures_collection(STRUCTURES_FILE, STRUCTURES / "raw")
    fema.add_child(structures)
    catalog.add_child(fema)

    catalog.set_self_href(str(DATA / "catalog.json"))
    landfire.set_self_href(str(LANDFIRE / "catalog.json"))
    fuels.set_self_href(str(STORE.with_suffix(".json")))
    fema.set_self_href(str(STRUCTURES / "catalog.json"))
    structures.set_self_href(str(STRUCTURES_FILE.with_suffix(".json")))
    catalog.make_all_asset_hrefs_relative()
    catalog.validate_all()
    catalog.save(pystac.CatalogType.SELF_CONTAINED)
    print(f"wrote {DATA / 'catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
