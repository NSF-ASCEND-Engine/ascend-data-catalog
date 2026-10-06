# cowy shared data

Shared datasets for the cowy project. Personal work stays in `/project/cowy/<user>/`.

## Layout

**`<source>/raw/`** holds vendor files as downloaded. Never modified.

**`<source>/derived/`** holds products built from `raw/`.

**`<source>/scripts/`** holds the code that builds `derived/`.

**`catalog.json`** and each **`<source>/catalog.json`** form a STAC catalog of `derived/`; see [STAC catalog](#stac-catalog).

Directories are group `cowy`, setgid. Ask a dataset's owner before changing it. The STAC `.json` files are written by `build_catalog.py`; don't edit them by hand.

## Datasets

| Dataset | Owner | Contents |
|---|---|---|
| `landfire/raw` | joshday | LANDFIRE CONUS zips, LF2016–LF2025 + disturbance |
| `landfire/derived/lf2025_fuels_terrain.zarr` | joshday | LF2025 fuels + LF2020 terrain, 23 layers, EPSG:5070, 30 m |
| `fema-usa-structures/raw` | joshday | FEMA/ORNL USA Structures File Geodatabase zips, 50 states + DC + 5 territories (2025 and 2026 deliverables) |
| `fema-usa-structures/derived/usa_structures.parquet` | joshday | 146M building footprints with occupancy, height, area and population attributes, GeoParquet 1.1, EPSG:4326 |

```python
import xarray as xr
ds = xr.open_zarr("/project/cowy/data/landfire/derived/lf2025_fuels_terrain.zarr")
```

The structures file has a `bbox` covering column and is Hilbert-sorted, so a bbox filter reads only the row groups it overlaps:

```python
import geopandas as gpd
gdf = gpd.read_parquet("/project/cowy/data/fema-usa-structures/derived/usa_structures.parquet",
                       bbox=(-105.3, 39.9, -105.2, 40.1))  # lon/lat
```

```sql
-- DuckDB
SELECT OCC_CLS, count(*) FROM '/project/cowy/data/fema-usa-structures/derived/usa_structures.parquet'
WHERE bbox.xmin < -105.2 AND bbox.xmax > -105.3 AND bbox.ymin < 40.1 AND bbox.ymax > 39.9
GROUP BY 1;
```

## STAC catalog

[STAC](https://stacspec.org) (SpatioTemporal Asset Catalog) is a JSON format for describing geospatial data: where it is, what area and time it covers, and how to read it. The catalog is metadata only. Its JSON files sit beside the data they describe.

### Layout

```
data/
├── catalog.json                              Catalog     cowy-data (root)
├── build_catalog.py
├── landfire/
│   ├── catalog.json                          Catalog     landfire, one per <source>/
│   └── derived/
│       ├── lf2025_fuels_terrain.zarr
│       └── lf2025_fuels_terrain.json         Collection  one per derived product, same name
└── fema-usa-structures/
    ├── catalog.json                          Catalog     fema-usa-structures
    └── derived/
        ├── usa_structures.parquet
        └── usa_structures.json               Collection
```

### Terms

| Term | Meaning | Here |
|---|---|---|
| **Catalog** | A JSON file that groups other Catalogs and Collections through `links`. It carries no spatial or temporal extent. | `catalog.json` (root), `landfire/catalog.json`, `fema-usa-structures/catalog.json` |
| **Collection** | A Catalog that describes one dataset: extent (bbox + time range), license, providers, keywords, and fields shared by everything in it. | `landfire/derived/lf2025_fuels_terrain.json` (id `lf2025-fuels-terrain`), `fema-usa-structures/derived/usa_structures.json` (id `usa-structures`) |
| **Item** | One spatiotemporal unit, such as a single scene or tile, as a GeoJSON Feature with its own geometry and datetime. Used when a dataset is many separate files. | none; each Zarr store is one aligned cube and the structures are one GeoParquet file, so each is an asset of its Collection |
| **Asset** | A link (`href`) to an actual data file or store, with a media `type` and `roles`. Assets belong to an Item or directly to a Collection. | `assets.zarr` → `./lf2025_fuels_terrain.zarr`, `assets.parquet` → `./usa_structures.parquet` |
| **Link** | A typed pointer between STAC files: `root`, `parent`, `child`, `item`, `license`. | all hrefs are relative, so paths resolve under `/project` and `/cluster/medbow/project` |
| **Extension** | A published schema that adds namespaced fields, listed in `stac_extensions`. | see below |

### Extensions used

- **Datacube** (`cube:dimensions`, `cube:variables`): the store's dimensions (`x`, `y` with extent, step, EPSG) and one entry per array (dtype, nodata, description, LANDFIRE product and release).
- **Projection** (`proj:code`, `proj:shape`, `proj:transform`, `proj:bbox`): the store's native grid, on the asset. The structures asset carries only `proj:code`.
- **xarray-assets** (`xarray:open_kwargs`): keyword arguments for `xarray.open_dataset`.
- **Table** (`table:columns`, `table:primary_geometry`, `table:row_count`): the GeoParquet file's columns, with Arrow types and FGDC attribute definitions from FEMA's metadata XML.

A Collection's `extent.spatial.bbox` is in WGS84 longitude/latitude, as STAC requires; LANDFIRE's `proj:bbox` and `cube:dimensions` are in the native CRS (EPSG:5070). The structures Collection lists an overall bbox, then sub-extents for CONUS and each state or territory outside it; Alaska's crosses the antimeridian, so its west bound is greater than its east bound.

### Reading

```python
import pystac, xarray as xr
cat = pystac.Catalog.from_file("/project/cowy/data/catalog.json")
fuels = cat.get_child("landfire").get_child("lf2025-fuels-terrain")
fuels.extra_fields["cube:variables"]["CBH"]  # dtype, nodata, description
zarr = fuels.assets["zarr"]
ds = xr.open_dataset(zarr.get_absolute_href(), **zarr.extra_fields["xarray:open_kwargs"])

structures = cat.get_child("fema-usa-structures").get_child("usa-structures")
{c["name"]: c.get("description") for c in structures.extra_fields["table:columns"]}
structures.assets["parquet"].get_absolute_href()
```

### Updating

Run `./build_catalog.py` after adding or changing a derived product; a new product needs a `*_collection` function and one `add_child` line in `main`. It reads each product's metadata (consolidated Zarr metadata, or the Parquet footer and row-group statistics), rewrites the JSON, and validates it against the STAC and extension schemas.

Each asset records `updated` (the file's or `zarr.json`'s modification time) and, for single files, `file:size`, so a rebuilt product shows up as a diff in the catalog even when its schema is unchanged.

## Git

This directory is the git repo [NSF-ASCEND-Engine/data](https://github.com/NSF-ASCEND-Engine/data). `.gitignore` ignores everything except the README, `build_catalog.py`, the STAC JSON and each `<source>/scripts/`; data, `raw/`, `derived/` stores and Slurm `*.out` logs are never committed. After changing a dataset, run `./build_catalog.py` and commit the scripts and JSON together.

The repo is owned by `joshday`, so other users must mark it safe once:

```sh
git config --global --add safe.directory /project/cowy/data
git config --global --add safe.directory /cluster/medbow/project/cowy/data
```
