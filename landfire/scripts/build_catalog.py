#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10", "pyproj>=3.6"]
# ///
"""Build the STAC Catalog of landfire/derived.

    landfire/scripts/build_catalog.py

Writes, beside the data:

    landfire/raw/catalog.json                 Collection of the raw zips, linked from ../raw.json
    landfire/derived/catalog.json             Catalog, linked from ../derived.json
    landfire/derived/<store>.json             one Collection per landfire/derived/<store>.zarr

raw/ is read-only; its owner's write bit is restored after catalog.json is written.

A store's Collection has a single ``zarr`` asset and datacube (cube:*) fields read
from the store's consolidated metadata; variable descriptions come from the
LANDFIRE metadata XML inside each array's source zip in ``raw/``, when that zip
is present.

All hrefs are relative, so the catalog resolves under both /project and
/cluster/medbow/project.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pystac
from pyproj import Transformer

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parent / "catalog.json"
STORE = SOURCE / "derived/lf2025_fuels_terrain.zarr"

DATACUBE = "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
PROJECTION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
XARRAY = "https://stac-extensions.github.io/xarray-assets/v1.0.0/schema.json"


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
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--metadata-from", type=Path, default=STORE,
                   help="read Zarr metadata from this copy of the store instead of the "
                        "published path (asset hrefs still point at the published path)")
    p.add_argument("--raw", type=Path, default=SOURCE / "raw",
                   help="LANDFIRE zips, for variable descriptions (default: landfire/raw)")
    args = p.parse_args(argv)

    raw = raw_collection(
        SOURCE / "raw", lambda n: "/General_Metadata/" in n and n.endswith(".xml"),
        id="landfire-raw",
        title="LANDFIRE (raw)",
        description="LANDFIRE (https://landfire.gov) CONUS product zips as downloaded, one asset per "
                    "zip: LF2016-LF2025 fuel, vegetation, disturbance and terrain layers plus the "
                    "annual and preliminary disturbance archives. Read-only.",
        keywords=["LANDFIRE", "fuels", "wildfire", "terrain", "CONUS"],
        providers=[pystac.Provider("LANDFIRE", roles=[pystac.ProviderRole.PRODUCER,
                                                      pystac.ProviderRole.LICENSOR],
                                   url="https://landfire.gov")],
    )
    raw.add_link(pystac.Link("license", "https://landfire.gov/data/faq",
                             media_type="text/html", title="LANDFIRE data use"))
    derived = pystac.Catalog(
        id="landfire-derived",
        title="LANDFIRE (derived)",
        description="Products built from `landfire/raw` by the code in `landfire/scripts`. "
                    "One Collection per store in `landfire/derived`.",
    )
    fuels = landfire_collection(STORE, args.metadata_from, args.raw)
    derived.add_child(fuels)
    save(raw, derived, {fuels: STORE.with_suffix(".json")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
