#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyogrio>=0.10", "pyarrow>=17"]
# ///
"""Merge the USA Structures state File Geodatabases into one GeoParquet file.

Each zip in raw/ is read in place through GDAL's /vsizip/, sorted along a
Hilbert curve, and written as GeoParquet 1.1 with a per-row ``bbox`` covering
column. The per-state files are then concatenated row group by row group into
one file, so every row group covers a compact area and bbox queries (DuckDB,
GeoPandas ``bbox=``, GDAL ``-spat``) skip the rest of the file.

    ./build_geoparquet.py --raw ../raw --out ../derived/usa_structures.parquet --workers 8

Geometry stays in the source CRS, EPSG:4326 (lon/lat).
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio


def gdb_path(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as z:
        gdbs = {n.split("/")[0] for n in z.namelist() if n.split("/")[0].endswith(".gdb")}
    if len(gdbs) != 1:
        raise ValueError(f"{zip_path.name}: expected one .gdb, found {sorted(gdbs)}")
    return f"/vsizip/{zip_path}/{gdbs.pop()}"


def convert_state(zip_path: Path, out: Path, row_group_size: int) -> tuple[str, int, float]:
    t0 = time.time()
    gdf = pyogrio.read_dataframe(gdb_path(zip_path), use_arrow=True)
    gdf = gdf.iloc[gdf.hilbert_distance().argsort()].reset_index(drop=True)
    gdf.to_parquet(
        out,
        compression="zstd",
        schema_version="1.1.0",
        write_covering_bbox=True,
        row_group_size=row_group_size,
    )
    return zip_path.name, len(gdf), time.time() - t0


def merge(parts: list[Path], out: Path) -> int:
    schema = pq.read_schema(parts[0])
    geo = json.loads(schema.metadata[b"geo"])
    col = geo["primary_column"]
    bboxes, types = [], set()
    for p in parts:
        g = json.loads(pq.read_schema(p).metadata[b"geo"])["columns"][col]
        bboxes.append(g["bbox"])
        types.update(g["geometry_types"])
    geo["columns"][col]["bbox"] = [
        min(b[0] for b in bboxes), min(b[1] for b in bboxes),
        max(b[2] for b in bboxes), max(b[3] for b in bboxes),
    ]
    geo["columns"][col]["geometry_types"] = sorted(types)
    schema = schema.with_metadata({**schema.metadata, b"geo": json.dumps(geo).encode()})

    tmp = out.with_suffix(".parquet.tmp")
    n = 0
    with pq.ParquetWriter(tmp, schema, compression="zstd", write_statistics=True) as w:
        for p in parts:
            f = pq.ParquetFile(p)
            for i in range(f.num_row_groups):
                t = f.read_row_group(i)
                if not t.schema.equals(schema, check_metadata=False):
                    t = t.cast(schema)  # raises if the state's fields differ
                w.write_table(t)
                n += t.num_rows
    tmp.rename(out)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scratch", type=Path, default=None, help="where per-state files go (default: a temp dir)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--row-group-size", type=int, default=100_000)
    args = ap.parse_args()

    zips = sorted(args.raw.glob("*.zip"), key=lambda p: p.stat().st_size, reverse=True)
    if not zips:
        raise SystemExit(f"no zips in {args.raw}")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=args.scratch) as d:
        parts = {z: Path(d) / f"{z.stem}.parquet" for z in zips}
        with ProcessPoolExecutor(args.workers) as ex:
            futs = [ex.submit(convert_state, z, parts[z], args.row_group_size) for z in zips]
            for f in as_completed(futs):
                name, n, dt = f.result()
                print(f"{name}: {n:,} structures in {dt:.0f} s", flush=True)
        n = merge([parts[z] for z in sorted(zips)], args.out)

    print(f"wrote {args.out}: {n:,} structures, {args.out.stat().st_size / 2**30:.1f} GiB")


if __name__ == "__main__":
    main()
