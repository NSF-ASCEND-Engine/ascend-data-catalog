"""STAC helpers shared by `<source>/scripts/build_catalog.py`.

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared/scripts"))
    from stac_raw import raw_collection, save

`raw_collection` describes `<source>/raw` as one Collection with one asset per
file; `save` writes it to `<source>/raw/catalog.json` and links it from
`../raw.json`, and does the same for an optional derived Catalog and
`../derived.json`. Other sources' JSON is left untouched.

All hrefs are relative, so the catalog resolves under both /project and
/cluster/medbow/project.
"""

from __future__ import annotations

import stat
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pystac

FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
PROJECTION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"

MEDIA_TYPES = {
    ".zip": "application/zip",
    ".tif": pystac.MediaType.COG,
    ".vrt": "application/xml",
    ".xml": "application/xml",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
METADATA_SUFFIXES = {".xml", ".pdf", ".xlsx"}


def mtime(path: Path) -> str:
    """Modification time as an RFC 3339 string, for an asset's ``updated`` field."""
    return pystac.utils.datetime_to_str(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))


def utc(date: str | None) -> datetime | None:
    """A ``YYYY-MM-DD`` date as a UTC datetime; ``None`` stays an open end."""
    return date and datetime.fromisoformat(date).replace(tzinfo=timezone.utc)


def file_asset(path: Path, title: str | None = None, **extra) -> pystac.Asset:
    return pystac.Asset(
        href=str(path),
        title=title or path.name,
        media_type=MEDIA_TYPES.get(path.suffix),
        roles=["metadata" if path.suffix in METADATA_SUFFIXES else "data"],
        extra_fields={"file:size": path.stat().st_size, "updated": mtime(path), **extra},
    )


def raw_collection(source: Path, *, bbox: list[float], interval: tuple[str | None, str | None],
                   license_url: str, license_title: str, license: str = "other",
                   asset_fields=lambda path: {}, stac_extensions=(), **kwargs) -> pystac.Collection:
    """A Collection with one asset per file in ``source/raw``.

    Assets are keyed by file stem, or by full name where two files share a stem.
    ``asset_fields(path)`` returns extra fields for one asset.
    """
    files = sorted(p for p in (source / "raw").iterdir() if p.is_file() and p.name != "catalog.json")
    stems = Counter(p.stem for p in files)
    collection = pystac.Collection(
        extent=pystac.Extent(pystac.SpatialExtent([bbox]),
                             pystac.TemporalExtent([[utc(interval[0]), utc(interval[1])]])),
        license=license,
        stac_extensions=[FILE, *stac_extensions],
        **kwargs,
    )
    collection.add_link(pystac.Link("license", license_url, media_type="text/html", title=license_title))
    for p in files:
        collection.add_asset(p.stem if stems[p.stem] == 1 else p.name, file_asset(p, **asset_fields(p)))
    return collection


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
    group.links.sort(key=lambda l: l.rel == "parent")  # keep the parent link after the children
    child.set_self_href(str(href))


def save(source: Path, raw: pystac.Collection, derived: pystac.Catalog | None = None,
         collections: dict[pystac.Collection, Path] | None = None) -> None:
    """Write ``raw/catalog.json`` and, if given, ``derived/catalog.json`` with its Collections."""
    source = source.resolve()
    groups = {c.id: c for c in pystac.Catalog.from_file(str(source.parent / "catalog.json")).get_children()}
    attach(groups["raw"], raw, source / "raw/catalog.json")
    raw.make_asset_hrefs_relative()
    raw.validate_all()
    if derived is not None:
        attach(groups["derived"], derived, source / "derived/catalog.json")
        for collection, href in (collections or {}).items():
            collection.set_self_href(str(href))
        derived.make_all_asset_hrefs_relative()
        derived.validate_all()
        derived.save(pystac.CatalogType.SELF_CONTAINED)
        groups["derived"].save_object(include_self_link=False)
    with writable(source / "raw"):
        raw.save_object(include_self_link=False)
    groups["raw"].save_object(include_self_link=False)
    print(f"wrote {source}/raw/catalog.json" + (f" and {source}/derived/catalog.json" if derived else ""))
