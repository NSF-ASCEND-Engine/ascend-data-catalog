# `landfire/`

[LANDFIRE](https://landfire.gov) CONUS raster products (fuels, vegetation, disturbance, terrain), as distributed by LANDFIRE and as one analysis-ready Zarr store. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/` | 51 LANDFIRE product zips as downloaded (113 GB, read-only): LF2016 (4), LF2020 (5), LF2023 (2), LF2024 (18), LF2025 (19), plus the annual, limited and preliminary disturbance archives. Each zip holds a GeoTIFF and FGDC metadata. |
| `raw/catalog.json` | STAC Collection `landfire-raw`, one asset per zip |
| `derived/lf2025_fuels_terrain.zarr` | 23 layers on one EPSG:5070 30 m grid (101538 × 156336), Zarr v3, 1024 × 1024 chunks |
| `derived/lf2025_fuels_terrain.json` | STAC Collection `lf2025-fuels-terrain`: per-layer dtype, nodata, description and LANDFIRE release |
| `derived/catalog.json` | STAC Catalog `landfire-derived` |
| `scripts/` | Code that builds `derived/` and the STAC JSON |

## `lf2025_fuels_terrain.zarr`

Arrays are named by bare LANDFIRE product code, each 2-D `(y, x)`:

- **LF2025 fuels and vegetation:** CBD, CBH, CC, CH, EVC, EVH, EVT, FBFM13, FBFM40, FCCS, FDist, FVC, FVH, FVT
- **LF2025 seasonal FBFM40 updates for 2026:** FBFM40_ES26, FBFM40_SP26, FBFM40_SU26
- **LF2025 annual disturbance:** LDist25 (limited), PDist25 (preliminary)
- **LF2020 terrain:** Elev, SlpD, SlpP, Asp. LANDFIRE does not reissue terrain each release; LF2020 and LF2025 share the same 30 m lattice, so no resampling was needed.

The grid is LF2020's extent, which is larger than LF2025's; LF2025 arrays read as fill in that margin. Nodata is in each array's `_FillValue` (32767 for most int16 layers, -9999 for Elev and Asp; SlpD and SlpP have none). Categorical layers (EVT, FBFM40, FCCS, …) carry LANDFIRE's value-attribute table as a list of row dicts in the array's `attribute_table` attribute. Each array also records its `source_zip` in `raw/`.

```python
import xarray as xr
from pyproj import Transformer

ds = xr.open_zarr("/project/cowy/data/landfire/derived/lf2025_fuels_terrain.zarr")

# Clip to a lon/lat box; x/y are EPSG:5070 metres and y decreases downward
x0, y0, x1, y1 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True) \
    .transform_bounds(-105.6, 39.9, -105.2, 40.2)
aoi = ds[["FBFM40", "CBH", "Elev"]].sel(x=slice(x0, x1), y=slice(y1, y0)).load()

# Fuel model names from the embedded attribute table
names = {int(r["VALUE"]): r["FBFM40"] for r in ds.FBFM40.attrs["attribute_table"]}
```

1024 × 1024 chunks suit 10–60 km AOI reads; see `scripts/landfire_to_zarr.py` for the chunk-size measurements.

## Rebuilding

```sh
sbatch scripts/build_lf2025_store.sh      # raw/ → derived/lf2025_fuels_terrain.zarr, ~10 min on one node
scripts/build_catalog.py                  # STAC JSON for raw/ and derived/; run by the owner of raw/
```

There is no download script; the zips in `raw/` were fetched from landfire.gov manually.
