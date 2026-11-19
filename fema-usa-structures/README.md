# `fema-usa-structures/`

The [FEMA/ORNL USA Structures](https://gis-fema.hub.arcgis.com/pages/usa-structures) building inventory: footprints of structures over 450 sq ft with occupancy, address, height, area, elevation and population estimates. Kept as the per-state File Geodatabase zips FEMA distributes, and as one GeoParquet file. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/` | 56 File Geodatabase zips as downloaded (26 GB, read-only): 50 states, DC and 5 territories, from FEMA's 2025 and 2026 deliverables. Each zip holds FGDC metadata. |
| `raw/catalog.json` | STAC Collection `fema-usa-structures-raw`, one asset per zip |
| `derived/usa_structures.parquet` | All 146,381,550 structures in one GeoParquet 1.1 file (29 GB), EPSG:4326 |
| `derived/usa_structures.json` | STAC Collection `usa-structures`: column names, Arrow types and FEMA's attribute definitions; per-region extents |
| `derived/catalog.json` | STAC Catalog `fema-usa-structures-derived` |
| `scripts/` | Code that downloads `raw/` and builds `derived/` and the STAC JSON |

## `usa_structures.parquet`

Rows are grouped by state and Hilbert-sorted within each state, and each row has a GeoParquet `bbox` covering column. A bbox or `PROP_ST` filter therefore reads only the row groups it overlaps instead of the full 29 GB.

Common columns: `OCC_CLS` and `PRIM_OCC` (occupancy class and type), `PROP_ADDR`, `PROP_CITY`, `PROP_ST` (state name), `PROP_ZIP`, `FIPS`, `HEIGHT`, `SQMETERS`, `SQFEET`, `H_ADJ_ELEV` / `L_ADJ_ELEV` (adjacent ground elevation), `POP_MEDIAN` with `POP_CI95_LOWER` / `POP_CI95_UPPER` (null outside residential occupancy), `IMAGE_DATE`, `BUILD_ID`, `UUID`, `geometry` (WKB polygon). Definitions for every column are in `derived/usa_structures.json` under `table:columns`.

### Python

```python
import geopandas as gpd

path = "/project/cowy/ascend-data-catalog/fema-usa-structures/derived/usa_structures.parquet"
gdf = gpd.read_parquet(path, bbox=(-105.3, 39.9, -105.2, 40.1))       # lon/lat
wy = gpd.read_parquet(path, columns=["OCC_CLS", "HEIGHT", "geometry"],
                      filters=[("PROP_ST", "=", "Wyoming")])
```

```sql
-- DuckDB
SELECT OCC_CLS, count(*), sum(POP_MEDIAN)
FROM '/project/cowy/ascend-data-catalog/fema-usa-structures/derived/usa_structures.parquet'
WHERE bbox.xmin < -105.2 AND bbox.xmax > -105.3 AND bbox.ymin < 40.1 AND bbox.ymax > 39.9
GROUP BY 1;
```

### Julia

Packages: `DuckDB`, `DataFrames`. `geometry` comes back as WKB bytes.

```julia
using DuckDB, DataFrames

path = "/project/cowy/ascend-data-catalog/fema-usa-structures/derived/usa_structures.parquet"
con = DBInterface.connect(DuckDB.DB)
df = DBInterface.execute(con, """
    SELECT OCC_CLS, HEIGHT, SQMETERS, POP_MEDIAN, geometry
    FROM '$path'
    WHERE bbox.xmin < -105.2 AND bbox.xmax > -105.3 AND bbox.ymin < 40.1 AND bbox.ymax > 39.9
    """) |> DataFrame
```

### R

On MedicineBow, load R with `module load arcc/1.0 gcc/15.2.0` then `module load r/4.5.3`. The module's library has no packages, so install them once into your own library; Posit's RHEL 9 binaries avoid compiling:

```r
options(repos = c(CRAN = "https://p3m.dev/cran/__linux__/rhel9/latest"),
        HTTPUserAgent = sprintf("R/%s R (%s)", getRversion(),
            paste(getRversion(), R.version["platform"], R.version["arch"], R.version["os"])))
install.packages(c("duckdb", "arrow", "dplyr"))
```

`geometry` comes back as a list of WKB raw vectors. `sf` and `terra` cannot read this file directly on MedicineBow: the cluster GDAL has no Parquet driver, and the `sf` binary needs system libraries the cluster lacks.

```r
library(duckdb)
library(arrow)
library(dplyr)

path <- "/project/cowy/ascend-data-catalog/fema-usa-structures/derived/usa_structures.parquet"

con <- dbConnect(duckdb())
df <- dbGetQuery(con, sprintf("
    SELECT OCC_CLS, HEIGHT, SQMETERS, POP_MEDIAN, geometry
    FROM '%s'
    WHERE bbox.xmin < -105.2 AND bbox.xmax > -105.3 AND bbox.ymin < 40.1 AND bbox.ymax > 39.9", path))

wy <- open_dataset(path) |>
    filter(PROP_ST == "Wyoming") |>
    select(OCC_CLS, HEIGHT, SQMETERS) |>
    collect()
```

Alaska's footprints span the antimeridian, so a bbox query there needs two boxes, one on each side of ±180°.

## Rebuilding

```sh
sbatch scripts/download_raw.sh            # zips listed in scripts/urls.txt → raw/; skips complete files
sbatch scripts/build_geoparquet.sh        # raw/ → derived/usa_structures.parquet
scripts/build_catalog.py                  # STAC JSON for raw/ and derived/; run by the owner of raw/
```

`scripts/download_raw.sh` documents how to refresh `scripts/urls.txt` from FEMA's hub page.
