#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10", "pyarrow>=17"]
# ///
"""Build the STAC Catalog of fema-usa-structures/derived.

    fema-usa-structures/scripts/build_catalog.py

Writes, beside the data:

    fema-usa-structures/raw/catalog.json      Collection of the raw zips, linked from ../raw.json
    fema-usa-structures/derived/catalog.json  Catalog, linked from ../derived.json
    fema-usa-structures/derived/<file>.json   one Collection per derived/<file>.parquet

raw/ is read-only; its owner's write bit is restored after catalog.json is written.

A GeoParquet file's Collection has a single ``parquet`` asset and table (table:*)
fields read from the Parquet footer; column descriptions come from the FGDC
metadata XML in a source zip.

All hrefs are relative, so the catalog resolves under both /project and
/cluster/medbow/project.
"""

from __future__ import annotations

import calendar
import json
import stat
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pystac

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parent / "catalog.json"
STRUCTURES_FILE = SOURCE / "derived/usa_structures.parquet"

PROJECTION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
TABLE = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"


#-----------------------------------------------------------------------------# GeoParquet
def mtime(path: Path) -> str:
    """Modification time as an RFC 3339 string, for an asset's ``updated`` field."""
    return pystac.utils.datetime_to_str(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))


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


#-----------------------------------------------------------------------------# Raw
def fgdc_date(s: str | None, end: bool) -> datetime | None:
    """An FGDC YYYY[MM[DD]] date; a bare year or month is widened to its first or last day."""
    if not s or not s[:4].isdigit():
        return None
    y, m, d = int(s[:4]), int(s[4:6] or (12 if end else 1)), int(s[6:8] or 0)
    if not d:
        d = calendar.monthrange(y, m)[1] if end else 1
    return datetime(y, m, d, *((23, 59, 59) if end else (0, 0, 0)), tzinfo=timezone.utc)


def fgdc_summary(zip_path: Path, is_metadata) -> tuple[str | None, list[float] | None, list | None]:
    """Title, WGS84 bbox and time period from the first FGDC XML in a zip matching ``is_metadata``."""
    with zipfile.ZipFile(zip_path) as zf:
        xml = [n for n in zf.namelist() if is_metadata(n)]
        if not xml:
            return None, None, None
        root = ET.fromstring(zf.read(xml[0]))
    b = root.find("idinfo/spdom/bounding")
    bbox = None if b is None else [float(b.findtext(k)) for k in ("westbc", "southbc", "eastbc", "northbc")]
    t = root.find("idinfo/timeperd/timeinfo")
    period = None if t is None else [fgdc_date(t.findtext(".//begdate"), False) or fgdc_date(t.findtext(".//caldate"), False),
                                     fgdc_date(t.findtext(".//enddate"), True) or fgdc_date(t.findtext(".//caldate"), True)]
    title = root.findtext("idinfo/citation/citeinfo/title")
    return title and " ".join(title.split()), bbox, period


def raw_collection(raw: Path, is_metadata, **kwargs) -> pystac.Collection:
    """A Collection with one asset per zip in ``raw``; extent is the union of the zips' FGDC metadata."""
    zips = sorted(raw.glob("*.zip"))
    summaries = {z: fgdc_summary(z, is_metadata) for z in zips}
    boxes = [b for _, b, _ in summaries.values() if b]
    starts = [p[0] for _, _, p in summaries.values() if p and p[0]]
    ends = [p[1] for _, _, p in summaries.values() if p and p[1]]
    bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    collection = pystac.Collection(
        extent=pystac.Extent(pystac.SpatialExtent([bbox]),
                             pystac.TemporalExtent([[min(starts, default=None), max(ends, default=None)]])),
        license="other",
        stac_extensions=[FILE],
        **kwargs,
    )
    for z in zips:
        collection.add_asset(z.stem, pystac.Asset(
            href=str(z),
            title=summaries[z][0] or z.stem,
            media_type="application/zip",
            roles=["data"],
            extra_fields={"file:size": z.stat().st_size, "updated": mtime(z)},
        ))
    return collection


#-----------------------------------------------------------------------------# Save
@contextmanager
def writable(directory: Path):
    """Temporarily add owner write permission to a read-only directory such as ``raw/``."""
    mode = directory.stat().st_mode
    directory.chmod(mode | stat.S_IWUSR)
    try:
        yield
    finally:
        directory.chmod(mode)


def attach(group: pystac.Catalog, child: pystac.Catalog, href: Path) -> None:
    """Link ``child`` (saved at ``href``) from ``group``, replacing an earlier link to ``href`` in place."""
    old = [i for i, l in enumerate(group.links)
           if l.rel == "child" and Path(l.get_absolute_href()).resolve() == href]
    group.links = [l for i, l in enumerate(group.links) if i not in old]
    link = group.add_child(child, title=child.title)
    if old:
        group.links.remove(link)
        group.links.insert(old[0], link)
    child.set_self_href(str(href))


def save(raw: pystac.Collection, derived: pystac.Catalog, collections: dict[pystac.Collection, Path]) -> None:
    """Write ``raw/catalog.json``, ``derived/catalog.json`` and its Collections, and link the two
    from ``../raw.json`` and ``../derived.json``. Other sources' JSON is left untouched.
    """
    groups = {c.id: c for c in pystac.Catalog.from_file(str(ROOT)).get_children()}
    attach(groups["raw"], raw, SOURCE / "raw/catalog.json")
    attach(groups["derived"], derived, SOURCE / "derived/catalog.json")
    for collection, href in collections.items():
        collection.set_self_href(str(href))
    raw.make_asset_hrefs_relative()
    derived.make_all_asset_hrefs_relative()
    raw.validate_all()
    derived.validate_all()
    with writable(SOURCE / "raw"):
        raw.save_object(include_self_link=False)
    derived.save(pystac.CatalogType.SELF_CONTAINED)
    for g in groups.values():
        g.save_object(include_self_link=False)
    print(f"wrote {SOURCE}/raw/catalog.json and {SOURCE}/derived/catalog.json")


#-----------------------------------------------------------------------------# Main
def main() -> int:
    raw = raw_collection(
        SOURCE / "raw", lambda n: n.endswith("_metadata.xml"),
        id="fema-usa-structures-raw",
        title="FEMA USA Structures (raw)",
        description="FEMA/ORNL USA Structures File Geodatabase zips as downloaded by "
                    "`scripts/download_raw.sh` from the URLs in `scripts/urls.txt`, one asset per "
                    "state or territory (50 states, DC, 5 territories; 2025 and 2026 deliverables). "
                    "Read-only. The bbox is the union of the zips' FGDC bounding boxes, so it spans "
                    "the antimeridian naively.",
        keywords=["buildings", "structures", "footprints", "FEMA"],
        providers=[
            pystac.Provider("Oak Ridge National Laboratory", roles=[pystac.ProviderRole.PRODUCER],
                            url="https://www.ornl.gov"),
            pystac.Provider("FEMA", roles=[pystac.ProviderRole.LICENSOR, pystac.ProviderRole.HOST],
                            url="https://gis-fema.hub.arcgis.com/pages/usa-structures"),
        ],
    )
    raw.add_link(pystac.Link("license", "https://gis-fema.hub.arcgis.com/pages/usa-structures",
                             media_type="text/html", title="USA Structures"))
    derived = pystac.Catalog(
        id="fema-usa-structures-derived",
        title="FEMA USA Structures (derived)",
        description="Products built from `fema-usa-structures/raw` by the code in "
                    "`fema-usa-structures/scripts`. One Collection per file in "
                    "`fema-usa-structures/derived`.",
    )
    structures = structures_collection(STRUCTURES_FILE, SOURCE / "raw")
    derived.add_child(structures)
    save(raw, derived, {structures: STRUCTURES_FILE.with_suffix(".json")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
