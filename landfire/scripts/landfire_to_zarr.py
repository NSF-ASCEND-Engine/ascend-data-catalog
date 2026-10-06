#!/usr/bin/env python3
r"""Build one Zarr store from a directory of LANDFIRE product zips.

Every product becomes a 2-D ``(y, x)`` array on a shared EPSG:5070 30 m grid,
with ``x``/``y`` coordinate arrays and a CF ``spatial_ref`` variable, so the
store opens directly with ``xarray.open_zarr`` / ``rioxarray``.

Products whose extent is smaller than the target grid are written into their
own window; the surrounding chunks are never written, so they cost no storage
and read back as the fill value.

``--release LF2024`` restricts the store to one LANDFIRE release and names the
arrays by their bare product code (CBD, EVT, FBFM40), so analysis code can move
between release stores unchanged.

Example -- the latest release plus terrain, chunked for per-fire extraction::

    ./landfire_to_zarr.py --out /path/lf2025_fuels_terrain.zarr \
        --release LF2025 --release LF2020 --short-names \
        --exclude 'LF2020_Dist*' --exclude 'LF2020_BPS*' \
        --chunk 1024 1024 --workers 16

That is the 19 LF2025 fuel and vegetation layers plus the four terrain layers
(Elev, SlpD, SlpP, Asp), which LANDFIRE last published under LF2020 and does not
reissue each release; the two --exclude patterns drop LF2020's disturbance and
BpS layers, which LF2025 supersedes. Both releases sit on the same 30 m lattice
with the same origin, so they co-register without resampling. The union grid is
LF2020's, 64 km wider and 38 km taller than LF2025's, and the LF2025 arrays read
as fill in that margin.

Why 1024 x 1024 chunks (2 MB raw; over land with no nodata a stored chunk runs
about 50 KB for the canopy layers to 900 KB for aspect): reading every layer
over a 10-60 km AOI -- the per-fire landscape these products feed -- takes
0.06-0.07 s on the project filesystem, against 0.08-0.10 s at 2048; point and
patch sampling is about 1.7x faster; and a sequential full scan still runs at
3.3 GB/s, against 4.1 GB/s at 2048. The trade is read amplification versus scan
throughput: a 30 km AOI decodes 4.1x the pixels it needs at 1024 and 9.3x at
2048, while dropping to 512 halves full-scan throughput. Prefer --chunk 512 512
if random patch sampling for model training dominates, --chunk 2048 2048 if
full-CONUS passes do. Chunk size barely affects stored size at any of these
settings. Add --shard 8192 8192 to cut the file count roughly 30x, at the cost
of one extra read for the shard index.

Requires: numpy, rasterio, zarr>=3, numcodecs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import zarr
from rasterio.windows import Window


# -----------------------------------------------------------------------------# Product discovery
@dataclass(frozen=True)
class Product:
    """One LANDFIRE raster, possibly nested inside a bundle zip."""

    name: str
    zip_path: str
    inner_zip: str | None  # member of zip_path that is itself a product zip
    tif: str  # member of the innermost zip
    csv: str | None  # value-attribute table, if the product ships one

    @property
    def vsi_path(self) -> str:
        if self.inner_zip is None:
            return f"/vsizip/{self.zip_path}/{self.tif}"
        return f"/vsizip//vsizip/{self.zip_path}/{self.inner_zip}/{self.tif}"


PRODUCT_RE = re.compile(r"^LF(\d{4})_(.+?)(?:_CONUS)?$")


def release_of(name: str) -> str | None:
    """The LANDFIRE release a product name belongs to, e.g. ``LF2024``."""
    m = PRODUCT_RE.match(name)
    return f"LF{m.group(1)}" if m else None


def array_names(products: list[Product], short: bool) -> dict[str, str]:
    """Map each product to the name its array takes in the store."""
    if not short:
        return {p.name: p.name for p in products}
    names = {p.name: (PRODUCT_RE.match(p.name).group(2) if PRODUCT_RE.match(p.name) else p.name)
             for p in products}
    taken: dict[str, str] = {}
    for full, short_name in names.items():
        if short_name in taken:
            raise SystemExit(f"--short-names would map {taken[short_name]} and {full} both to "
                             f"{short_name!r}; pass --full-names")
        taken[short_name] = full
    return names


def _members(names: list[str], suffix: str, folder: str | None = None) -> list[str]:
    hits = [n for n in names if n.lower().endswith(suffix)]
    if folder is not None:
        hits = [n for n in hits if f"/{folder}/" in n]
    return sorted(hits)


def _product_from_names(name: str, zip_path: Path, inner: str | None, names: list[str]) -> Product | None:
    tifs = _members(names, ".tif", "Tif") or _members(names, ".tif")
    if not tifs:
        return None
    csvs = _members(names, ".csv", "CSV_Data")
    return Product(name, str(zip_path), inner, tifs[0], csvs[0] if csvs else None)


def scan_zip(zp: Path) -> list[Product]:
    """Products in one zip: either the zip itself, or the product zips it bundles."""
    with zipfile.ZipFile(zp) as zf:
        names = zf.namelist()
        direct = _product_from_names(zp.stem, zp, None, names)
        if direct is not None:
            return [direct]
        out = []
        for inner in _members(names, ".zip"):
            with zf.open(inner) as fh:  # deflated, so it has to be read to be listed
                inner_names = zipfile.ZipFile(io.BytesIO(fh.read())).namelist()
            prod = _product_from_names(Path(inner).stem, zp, inner, inner_names)
            if prod is not None:
                out.append(prod)
        return out


# -----------------------------------------------------------------------------# Target grid
@dataclass(frozen=True)
class Grid:
    x0: float
    y0: float
    width: int
    height: int
    res: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0 - self.height * self.res, self.x0 + self.width * self.res, self.y0)

    def offset_of(self, src: "SourceGrid") -> tuple[int, int]:
        """Column/row offset of *src*'s origin within this grid."""
        col = (src.x0 - self.x0) / self.res
        row = (self.y0 - src.y0) / self.res
        if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
            raise ValueError(f"{src.name} is not aligned to the target pixel lattice")
        return round(col), round(row)


@dataclass(frozen=True)
class SourceGrid:
    name: str
    x0: float
    y0: float
    width: int
    height: int
    res: float
    crs: str
    dtype: str
    nodata: float | None


def read_source_grid(prod: Product) -> SourceGrid:
    with rasterio.open(prod.vsi_path) as ds:
        t = ds.transform
        if t.b or t.d:
            raise ValueError(f"{prod.name}: rotated transforms are not supported")
        if abs(t.a) != abs(t.e):
            raise ValueError(f"{prod.name}: non-square pixels {t.a}x{t.e}")
        return SourceGrid(prod.name, t.c, t.f, ds.width, ds.height, abs(t.a),
                          ds.crs.to_string() if ds.crs else "", ds.dtypes[0], ds.nodata)


def build_catalog(src: Path, cache_path: Path | None) -> dict[str, tuple[Product, SourceGrid]]:
    """List every product under *src* and read its georeferencing.

    Listing the bundle zips means decompressing them, so results are memoised in
    a JSON sidecar keyed by each zip's size and mtime.
    """
    cache: dict[str, list] = {}
    if cache_path is not None and cache_path.exists():
        cache = json.loads(cache_path.read_text())
    catalog: dict[str, tuple[Product, SourceGrid]] = {}
    nested: dict[str, tuple[Product, SourceGrid]] = {}
    dirty = False
    for zp in sorted(src.glob("*.zip")):
        stat = os.stat(zp)
        key = f"{zp.name}|{stat.st_size}|{int(stat.st_mtime)}"
        if key not in cache:
            print(f"  scanning {zp.name}", flush=True)
            cache[key] = [[asdict(p), asdict(read_source_grid(p))] for p in scan_zip(zp)]
            dirty = True
        for prod_d, grid_d in cache[key]:
            prod, grid = Product(**prod_d), SourceGrid(**grid_d)
            target = nested if prod.inner_zip is not None else catalog
            target.setdefault(prod.name, (prod, grid))
    if cache_path is not None and dirty:
        try:
            cache_path.write_text(json.dumps(cache, indent=1))
        except OSError as exc:  # a read-only source directory is not fatal
            print(f"  warning: could not cache the scan at {cache_path}: {exc}", flush=True)
    # A standalone product zip wins over the same product inside a bundle.
    return {**nested, **catalog}


def build_grid(grids: dict[str, SourceGrid], mode: str, bounds: tuple[float, ...] | None) -> Grid:
    res = {g.res for g in grids.values()}
    crs = {g.crs for g in grids.values()}
    if len(res) != 1:
        raise SystemExit(f"mixed resolutions {sorted(res)}; reproject before converting")
    if len(crs) != 1:
        raise SystemExit(f"mixed CRSs {sorted(crs)}; reproject before converting")
    r = res.pop()
    lefts = [g.x0 for g in grids.values()]
    tops = [g.y0 for g in grids.values()]
    rights = [g.x0 + g.width * r for g in grids.values()]
    bottoms = [g.y0 - g.height * r for g in grids.values()]
    if bounds is not None:
        ref = min(lefts), max(tops)  # snap the requested box onto the shared lattice
        x0 = ref[0] + np.floor((bounds[0] - ref[0]) / r) * r
        y1 = ref[1] - np.floor((ref[1] - bounds[3]) / r) * r
        x1 = ref[0] + np.ceil((bounds[2] - ref[0]) / r) * r
        y0 = ref[1] - np.ceil((ref[1] - bounds[1]) / r) * r
    elif mode == "intersection":
        x0, y1, x1, y0 = max(lefts), min(tops), min(rights), max(bottoms)
    else:
        x0, y1, x1, y0 = min(lefts), max(tops), max(rights), min(bottoms)
    width, height = round((x1 - x0) / r), round((y1 - y0) / r)
    if width <= 0 or height <= 0:
        raise SystemExit("target grid is empty")
    return Grid(float(x0), float(y1), width, height, r)


# -----------------------------------------------------------------------------# Zarr encoding options
def make_compressors(args, zarr_format: int):
    """Translate the CLI compression flags into zarr v2 or v3 codecs."""
    if args.compressor == "none":
        return None
    if zarr_format == 3:
        from zarr.codecs import BloscCodec, GzipCodec, ZstdCodec

        if args.compressor == "blosc":
            return [BloscCodec(cname=args.cname, clevel=args.clevel, shuffle=args.shuffle)]
        if args.compressor == "zstd":
            return [ZstdCodec(level=args.clevel)]
        return [GzipCodec(level=args.clevel)]
    import numcodecs

    if args.compressor == "blosc":
        shuffle = {"noshuffle": 0, "shuffle": 1, "bitshuffle": 2}[args.shuffle]
        return [numcodecs.Blosc(cname=args.cname, clevel=args.clevel, shuffle=shuffle)]
    if args.compressor == "zstd":
        return [numcodecs.Zstd(level=args.clevel)]
    return [numcodecs.GZip(level=args.clevel)]


def read_attribute_table(prod: Product) -> list[dict] | None:
    if prod.csv is None:
        return None
    with zipfile.ZipFile(prod.zip_path) as zf:
        if prod.inner_zip is not None:
            with zf.open(prod.inner_zip) as fh:
                zf = zipfile.ZipFile(io.BytesIO(fh.read()))
        with zf.open(prod.csv) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text))


def crs_attrs(crs_str: str) -> dict:
    crs = rasterio.crs.CRS.from_string(crs_str)
    attrs = {"spatial_ref": crs.to_wkt(), "crs_wkt": crs.to_wkt()}
    if crs.to_epsg():
        attrs["epsg_code"] = crs.to_epsg()
    return attrs


def init_store(out: Path, grid: Grid, products, grids, names, args) -> zarr.Group:
    """Create the group, coordinate variables and one empty array per product."""
    fmt = args.zarr_format
    root = zarr.open_group(str(out), mode="a", zarr_format=fmt)
    transform = [grid.res, 0.0, grid.x0, 0.0, -grid.res, grid.y0]
    existing = root.attrs.get("transform")
    if existing is not None and list(existing) != transform:
        raise SystemExit(f"{out} was built on a different grid ({existing}); "
                         f"use a new path or pass matching --grid/--bounds")
    root.attrs.update({
        "Conventions": "CF-1.8",
        "title": "LANDFIRE CONUS products",
        "source": str(args.src),
        "history": f"{time.strftime('%Y-%m-%dT%H:%M:%S')} landfire_to_zarr.py",
        "crs": next(iter(grids.values())).crs,
        "resolution": grid.res,
        "transform": transform,
        **({"releases": sorted(args.release)} if args.release else {}),
    })

    coords = {
        "x": grid.x0 + (np.arange(grid.width) + 0.5) * grid.res,
        "y": grid.y0 - (np.arange(grid.height) + 0.5) * grid.res,
    }
    for dim, values in coords.items():
        if dim in root:
            continue
        arr = zarr.create_array(store=str(out), name=dim, shape=values.shape, dtype="float64",
                                chunks=values.shape, compressors=make_compressors(args, fmt),
                                zarr_format=fmt, overwrite=True,
                                **({"dimension_names": (dim,)} if fmt == 3 else {}))
        arr[:] = values
        arr.attrs.update({
            "_ARRAY_DIMENSIONS": [dim],
            "standard_name": f"projection_{'x' if dim == 'x' else 'y'}_coordinate",
            "units": "m",
        })

    if "spatial_ref" not in root:
        ref = zarr.create_array(store=str(out), name="spatial_ref", shape=(), dtype="int32",
                                compressors=None, zarr_format=fmt, overwrite=True)
        ref[()] = 0
        ref.attrs.update({"_ARRAY_DIMENSIONS": [], **crs_attrs(next(iter(grids.values())).crs)})

    for prod in products:
        src = grids[prod.name]
        if names[prod.name] in root and not args.overwrite:
            continue
        fill = src.nodata if src.nodata is not None else args.fill_value
        dtype = np.dtype(src.dtype)
        arr = zarr.create_array(
            store=str(out), name=names[prod.name], shape=(grid.height, grid.width), dtype=dtype,
            chunks=(args.chunk[0], args.chunk[1]),
            shards=tuple(args.shard) if args.shard else None,
            compressors=make_compressors(args, fmt),
            fill_value=dtype.type(fill) if fill is not None else None,
            zarr_format=fmt, overwrite=True,
            **({"dimension_names": ("y", "x")} if fmt == 3 else {}),
        )
        attrs = {
            "_ARRAY_DIMENSIONS": ["y", "x"],
            "grid_mapping": "spatial_ref",
            "long_name": prod.name,
            "landfire_product": prod.name,
            "landfire_release": release_of(prod.name),
            "source_zip": Path(prod.zip_path).name,
            "source_tif": prod.tif,
            "source_shape": [src.height, src.width],
            "landfire_complete": False,
        }
        if src.nodata is not None:
            attrs["_FillValue"] = dtype.type(src.nodata).item()
        if args.attribute_tables:
            table = read_attribute_table(prod)
            if table:
                attrs["attribute_table"] = table
        arr.attrs.update(attrs)
    return root


# -----------------------------------------------------------------------------# Progress reporting
try:  # a bar drawn in block characters needs a terminal that can encode them
    "\u2588\u2591".encode(sys.stdout.encoding or "ascii")
    FULL, EMPTY = "\u2588", "\u2591"
except (UnicodeEncodeError, LookupError):
    FULL, EMPTY = "#", "-"


def fmt_dur(seconds: float) -> str:
    h, rem = divmod(int(max(seconds, 0)), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class Progress:
    """One self-updating line on a terminal, periodic plain lines in a log file."""

    WIDTH = 24

    def __init__(self, total: float, prefix: str, unit: str, interval: float, scale: float = 1.0):
        self.total = max(float(total), 1.0)
        self.prefix, self.unit, self.interval, self.scale = prefix, unit, interval, scale
        self.done = 0.0
        self.t0 = self.last = time.time()
        self.tty = sys.stdout.isatty()
        self.printed = 0
        if self.interval and self.tty:
            self._write(self._line())

    def advance(self, amount: float = 1.0) -> None:
        """Record progress, redrawing at most 10x a second on a terminal."""
        self.done += amount
        if not self.interval:
            return
        now = time.time()
        # A log file gets a line every --progress seconds; a terminal redraws in place.
        if now - self.last >= (0.1 if self.tty else self.interval):
            self.last = now
            self._write(self._line(bar=self.tty), end="\r" if self.tty else "\n")

    def close(self, note: str) -> None:
        if self.interval:
            self._write(f"{self.prefix} {note} in {fmt_dur(time.time() - self.t0)}", end="\n")

    def _line(self, bar: bool = True) -> str:
        frac = min(self.done / self.total, 1.0)
        elapsed = time.time() - self.t0
        rate = self.done / elapsed if elapsed > 0 else 0.0
        eta = (self.total - self.done) / rate if rate > 0 else 0.0
        filled = round(self.WIDTH * frac)
        drawn = f"{FULL * filled}{EMPTY * (self.WIDTH - filled)} " if bar else ""
        return (f"{self.prefix} {drawn}{frac:4.0%}  {self.done / self.scale:.2f}/"
                f"{self.total / self.scale:.2f} {self.unit}  {rate / self.scale:.2f} {self.unit}/s"
                f"  eta {fmt_dur(eta)}")

    def _write(self, line: str, end: str = "\r") -> None:
        sys.stdout.write(line + " " * max(0, self.printed - len(line)) + end)
        sys.stdout.flush()
        self.printed = 0 if end == "\n" else len(line)


# -----------------------------------------------------------------------------# Extraction
def _copy_member(zf: zipfile.ZipFile, member: str, dest: Path, prefix: str, interval: float) -> None:
    """Stream one zip member to disk, reporting progress against its stored size."""
    total = zf.getinfo(member).file_size
    bar = Progress(total, prefix, "GB", interval, 1e9)
    with zf.open(member) as fh, open(dest, "wb") as out:
        while block := fh.read(16 << 20):
            out.write(block)
            bar.advance(len(block))
    bar.close(f"{total / 1e9:.2f} GB")


def extract_tif(prod: Product, scratch: Path, prefix: str = "", interval: float = 0) -> Path:
    """Copy a product's GeoTIFF out of its (possibly nested) zip."""
    scratch.mkdir(parents=True, exist_ok=True)
    dest = scratch / f"{prod.name}.tif"
    with zipfile.ZipFile(prod.zip_path) as zf:
        if prod.inner_zip is not None:
            inner = scratch / f"{prod.name}.inner.zip"
            _copy_member(zf, prod.inner_zip, inner, f"{prefix} unbundling", interval)
            zf = zipfile.ZipFile(inner)
        _copy_member(zf, prod.tif, dest, f"{prefix} extracting", interval)
    if prod.inner_zip is not None:
        (scratch / f"{prod.name}.inner.zip").unlink(missing_ok=True)
    return dest


# -----------------------------------------------------------------------------# Block copy
_WORKER: dict = {}


def _worker_init(store_path: str, array_name: str, tif_path: str):
    _WORKER["array"] = zarr.open_array(store=store_path, path=array_name, mode="r+")
    _WORKER["src"] = rasterio.open(tif_path)


def _copy_band(band: tuple[int, int, int, int, int, int]) -> int:
    """Copy one horizontal band of target blocks. Returns source pixels copied."""
    y0, y1, step_x, off_col, off_row, width = band
    arr, src = _WORKER["array"], _WORKER["src"]
    fill = arr.fill_value
    written = 0
    for x0 in range(0, width, step_x):
        x1 = min(x0 + step_x, width)
        # Overlap of this target block with the source raster, in source pixels.
        sx0, sx1 = max(x0 - off_col, 0), min(x1 - off_col, src.width)
        sy0, sy1 = max(y0 - off_row, 0), min(y1 - off_row, src.height)
        if sx0 >= sx1 or sy0 >= sy1:
            continue
        data = src.read(1, window=Window(sx0, sy0, sx1 - sx0, sy1 - sy0))
        written += data.size
        if (sx1 - sx0, sy1 - sy0) != (x1 - x0, y1 - y0):
            block = np.full((y1 - y0, x1 - x0), fill if fill is not None else 0, dtype=data.dtype)
            block[sy0 + off_row - y0: sy1 + off_row - y0, sx0 + off_col - x0: sx1 + off_col - x0] = data
            data = block
        arr[y0:y1, x0:x1] = data
    return written


def covered(src: SourceGrid, grid: Grid) -> int:
    """Target pixels the source actually covers, after clipping to the grid."""
    col, row = grid.offset_of(src)
    return (max(0, min(col + src.width, grid.width) - max(col, 0))
            * max(0, min(row + src.height, grid.height) - max(row, 0)))


def convert(prod: Product, name: str, src: SourceGrid, grid: Grid, tif: Path, out: Path, args,
            prefix: str = "") -> None:
    off_col, off_row = grid.offset_of(src)
    # Work in whole shards when sharding, otherwise whole chunks, so that no
    # write ever has to read back and re-encode a partially filled block.
    band_h, step_x = (args.shard if args.shard else args.chunk)
    # Only bands that intersect the source footprint need visiting.
    lo = max(off_row // band_h * band_h, 0)
    hi = min(off_row + src.height, grid.height)
    bands = [(y, min(y + band_h, grid.height), step_x, off_col, off_row, grid.width)
             for y in range(lo, hi, band_h)]
    total = covered(src, grid)
    bar = Progress(total, f"{prefix} writing", "Gpx", args.progress, 1e9)
    with ProcessPoolExecutor(args.workers, initializer=_worker_init,
                             initargs=(str(out), name, str(tif))) as pool:
        futures = [pool.submit(_copy_band, b) for b in bands]
        for fut in as_completed(futures):
            bar.advance(fut.result())
    bar.close(f"{total / 1e9:.2f} Gpx")
    arr = zarr.open_array(store=str(out), path=name, mode="r+")
    arr.attrs["landfire_complete"] = True


# -----------------------------------------------------------------------------# CLI
def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", type=Path, default=Path.cwd(), help="directory of LANDFIRE zips (default: cwd)")
    p.add_argument("--out", type=Path, required=True, help="output Zarr store path")

    sel = p.add_argument_group("product selection")
    sel.add_argument("--release", action="append", default=[], metavar="LFYYYY",
                     help="only convert products from this LANDFIRE release, e.g. LF2024 "
                          "(repeatable; a bare year works too)")
    sel.add_argument("--include", action="append", default=[], metavar="GLOB",
                     help="only convert products matching this glob (repeatable)")
    sel.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                     help="skip products matching this glob (repeatable)")
    sel.add_argument("--limit", type=int, help="stop after N products (for testing)")
    sel.add_argument("--short-names", dest="short_names", action="store_true", default=None,
                     help="name arrays by the bare product code (CBD, Elev) instead of the full "
                          "product name; the default when exactly one --release is given")
    sel.add_argument("--full-names", dest="short_names", action="store_false",
                     help="keep full product names (LF2024_CBD_CONUS) even for a single --release")

    g = p.add_argument_group("target grid")
    g.add_argument("--grid", choices=("union", "intersection", "all"), default="union",
                   help="union: extent covering the selected products (default). intersection: "
                        "only their common area. all: union over every product in --src, so that "
                        "separately converted subsets share one geometry")
    g.add_argument("--bounds", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                   help="explicit extent in the product CRS; snapped to the shared pixel lattice")

    z = p.add_argument_group("zarr encoding")
    z.add_argument("--zarr-format", type=int, choices=(2, 3), default=3)
    # 1024 balances the two access patterns measured on the VAST project filesystem: a
    # per-fire AOI read (10-60 km, all layers) is faster than at 2048, point/patch sampling
    # is ~1.7x faster, and a sequential full scan still runs at 3.3 GB/s against 4.1 at 2048.
    z.add_argument("--chunk", type=int, nargs=2, default=(1024, 1024), metavar=("Y", "X"),
                   help="chunk shape in pixels (default: 1024 1024)")
    z.add_argument("--shard", type=int, nargs=2, metavar=("Y", "X"),
                   help="shard shape in pixels; zarr format 3 only, must be a whole multiple of "
                        "--chunk. Shards are written whole, so each worker holds one in memory")
    # Measured on 2048x2048 chunks of seven CONUS products: blosc/zstd/5 with byte shuffle
    # stores 7.8% of raw, against 8.3% for plain zstd-5 and 8.1% for zstd-9, and decodes
    # faster than either. Level 7 buys nothing; level 9 saves a further 12% at 1/14 the
    # encode speed.
    z.add_argument("--compressor", choices=("blosc", "zstd", "gzip", "none"), default="blosc")
    z.add_argument("--cname", choices=("zstd", "lz4", "lz4hc", "blosclz", "zlib"), default="zstd",
                   help="blosc inner codec (default: zstd)")
    z.add_argument("--clevel", type=int, default=5, help="compression level (default: 5)")
    z.add_argument("--shuffle", choices=("noshuffle", "shuffle", "bitshuffle"), default="shuffle",
                   help="blosc byte/bit shuffle filter (default: shuffle)")
    z.add_argument("--fill-value", type=float, default=0,
                   help="fill value for products whose GeoTIFF declares no nodata (default: 0)")
    z.add_argument("--no-attribute-tables", dest="attribute_tables", action="store_false",
                   help="do not embed the LANDFIRE value-attribute CSVs in array attributes")

    r = p.add_argument_group("execution")
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2),
                   help="processes copying blocks in parallel")
    r.add_argument("--scratch", type=Path, help="directory for extracted GeoTIFFs (default: <out>.scratch)")
    r.add_argument("--no-extract", dest="extract", action="store_false",
                   help="read GeoTIFFs in place through /vsizip instead of extracting "
                        "(no scratch space needed, substantially slower)")
    r.add_argument("--overwrite", action="store_true", help="rewrite arrays that are already complete")
    r.add_argument("--catalog-cache", type=Path, metavar="PATH",
                   help="where to memoise the zip scan (default: <src>/.landfire_catalog.json)")
    r.add_argument("--rescan", action="store_true", help="ignore the cached zip scan")
    r.add_argument("--progress", type=float, default=30, metavar="SECONDS",
                   help="on a terminal, draw a progress bar; in a log file, print a progress "
                        "line this often. 0 silences both (default: 30)")
    r.add_argument("--dry-run", action="store_true", help="print the plan and exit")

    args = p.parse_args(argv)
    args.release = [r if r.upper().startswith("LF") else f"LF{r}" for r in args.release]
    args.release = [r.upper() for r in args.release]
    if args.short_names is None:
        args.short_names = len(args.release) == 1
    if args.shard:
        if args.zarr_format != 3:
            p.error("--shard requires --zarr-format 3")
        if args.shard[0] % args.chunk[0] or args.shard[1] % args.chunk[1]:
            p.error("--shard must be a whole multiple of --chunk")
    return args


def select(products: list[Product], args) -> list[Product]:
    from fnmatch import fnmatch

    keep = [p for p in products
            if (not args.release or release_of(p.name) in args.release)
            and (not args.include or any(fnmatch(p.name, g) for g in args.include))
            and not any(fnmatch(p.name, g) for g in args.exclude)]
    return keep[: args.limit] if args.limit else keep


def main(argv=None) -> int:
    args = parse_args(argv)
    args.src = args.src.resolve()
    args.out = args.out.resolve()
    scratch = (args.scratch or Path(f"{args.out}.scratch")).resolve()

    cache = args.catalog_cache or args.src / ".landfire_catalog.json"
    if args.rescan:
        cache.unlink(missing_ok=True)
    print(f"scanning {args.src}", flush=True)
    catalog = build_catalog(args.src, cache)
    products = select(sorted((p for p, _ in catalog.values()), key=lambda p: p.name), args)
    if not products:
        raise SystemExit("no LANDFIRE products matched")
    grids = {p.name: catalog[p.name][1] for p in products}
    names = array_names(products, args.short_names)
    scope = {n: g for n, (_, g) in catalog.items()} if args.grid == "all" else grids
    grid = build_grid(scope, args.grid, args.bounds)

    nbytes = sum(np.dtype(grids[p.name].dtype).itemsize for p in products) * grid.width * grid.height
    label = "+".join(sorted(args.release)) + " " if args.release else ""
    print(f"\n{len(products)} {label}products -> {args.out}")
    print(f"  grid   {grid.height} x {grid.width} @ {grid.res:g} m, bounds {tuple(round(b) for b in grid.bounds)}")
    print(f"  chunks {tuple(args.chunk)}" + (f", shards {tuple(args.shard)}" if args.shard else ""))
    print(f"  codec  {args.compressor}" + (f"/{args.cname} clevel={args.clevel} {args.shuffle}"
                                           if args.compressor == "blosc" else f" clevel={args.clevel}"))
    print(f"  uncompressed size {nbytes / 1e12:.2f} TB across {len(products)} arrays\n")
    width = max(len(n) for n in names.values())
    clipped = []
    for p in products:
        s = grids[p.name]
        col, row = grid.offset_of(s)
        kept = (max(0, min(col + s.width, grid.width) - max(col, 0))
                * max(0, min(row + s.height, grid.height) - max(row, 0))) / (s.width * s.height)
        if kept < 0.9999:
            clipped.append((names[p.name], kept))
        print(f"    {names[p.name]:{width}s} {s.height:6d} x {s.width:6d}  {s.dtype:7s} "
              f"nodata={s.nodata}" + (f"  <- {p.name}" if names[p.name] != p.name else "")
              + (f"  [target grid keeps {kept:.1%}]" if kept < 0.9999 else ""))
    if clipped:
        print(f"\n  warning: the target grid discards part of {len(clipped)} product(s), "
              f"down to {min(k for _, k in clipped):.1%} for {min(clipped, key=lambda c: c[1])[0]}. "
              f"Regional products (the seasonal FBFM40 tiles) shrink a --grid intersection to "
              f"their own footprint; --exclude them or use --grid union.")
    if args.dry_run:
        return 0

    root = init_store(args.out, grid, products, grids, names, args)
    start, pending = time.time(), sum(covered(grids[p.name], grid) for p in products)
    for i, prod in enumerate(products, 1):
        name = names[prod.name]
        tag = f"[{i}/{len(products)}] {name:{width}s}"
        if root[name].attrs.get("landfire_complete") and not args.overwrite:
            print(f"{tag} already complete, skipping", flush=True)
            pending -= covered(grids[prod.name], grid)
            continue
        t0 = time.time()
        tif = extract_tif(prod, scratch, tag, args.progress) if args.extract else Path(prod.vsi_path)
        try:
            convert(prod, name, grids[prod.name], grid, tif, args.out, args, tag)
        finally:
            if args.extract:
                tif.unlink(missing_ok=True)
        pending -= covered(grids[prod.name], grid)
        done_px = sum(covered(grids[p.name], grid) for p in products) - pending
        eta = (time.time() - start) / max(done_px, 1) * pending
        print(f"{tag} done in {fmt_dur(time.time() - t0)}"
              + (f"  ({fmt_dur(eta)} left)" if pending else ""), flush=True)

    zarr.consolidate_metadata(str(args.out))
    if scratch.exists() and not any(scratch.iterdir()):
        scratch.rmdir()
    print(f"\nwrote {args.out} in {fmt_dur(time.time() - start)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
