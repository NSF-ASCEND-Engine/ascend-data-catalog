# `tiger/`

[Census TIGER/Line 2026](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) boundary and transportation shapefiles, as distributed by the Census Bureau. Boundaries are as of January 1, 2026. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/` | 232 shapefile zips as downloaded (2.3 GB, read-only), EPSG:4269 |
| `raw/catalog.json` | STAC Collection `tiger-raw`, one asset per zip |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`; the zips read directly.

## Layers

| Layer | File | Contents |
|---|---|---|
| `state`, `county` | `tl_2026_us_<layer>.zip` | States, counties and equivalents |
| `zcta520`, `uac20`, `cbsa`, `aiannh` | `tl_2026_us_<layer>.zip` | 2020 ZIP Code Tabulation Areas, 2020 urban areas, core based statistical areas, tribal areas |
| `primaryroads`, `rails` | `tl_2026_us_<layer>.zip` | Primary roads, railroads |
| `tract`, `bg`, `place`, `prisecroads` | `tl_2026_<FIPS>_<layer>.zip` | Census tracts, block groups, places, primary and secondary roads; one zip per state or territory (Colorado is `08`, Wyoming `56`) |

Per-county layers (all roads, edges, area and linear water, address ranges) and census blocks are not mirrored; they follow the same pattern under `https://www2.census.gov/geo/tiger/TIGER2026/`.

### Python

```python
import geopandas as gpd

raw = "/project/cowy/ascend-data-catalog/tiger/raw"
counties = gpd.read_file(f"{raw}/tl_2026_us_county.zip")            # 3,235 rows
wy = counties[counties.STATEFP == "56"]
tracts = gpd.read_file(f"{raw}/tl_2026_56_tract.zip")               # join to other data on GEOID
```

### Julia

Packages: `GeoDataFrames`, `DataFrames`.

```julia
using GeoDataFrames, DataFrames

raw = "/project/cowy/ascend-data-catalog/tiger/raw"
counties = GeoDataFrames.read("/vsizip/$raw/tl_2026_us_county.zip")     # 3,235 rows
wy = counties[counties.STATEFP .== "56", :]
tracts = GeoDataFrames.read("/vsizip/$raw/tl_2026_56_tract.zip")        # join to other data on GEOID
```

### R

On MedicineBow, load R and the cluster GDAL in every session with `module load arcc/1.0 gcc/15.2.0` then `module load r/4.5.3 gdal/3.13.0 geos/3.14.1 proj/9.7.0`. Install `terra` once into your own library, from source so that it links to the cluster GDAL:

```r
install.packages("terra", repos = "https://cloud.r-project.org")
```

```r
library(terra)

raw <- "/project/cowy/ascend-data-catalog/tiger/raw"
counties <- vect(paste0("/vsizip/", raw, "/tl_2026_us_county.zip"))     # 3,235 rows
wy <- counties[counties$STATEFP == "56", ]
tracts <- vect(paste0("/vsizip/", raw, "/tl_2026_56_tract.zip"))        # join to other data on GEOID
```

## Rebuilding

```sh
sbatch --job-name=tiger-dl ../_shared/scripts/download_raw.sh tiger   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                              # STAC JSON for raw/; run by the owner of raw/
```
