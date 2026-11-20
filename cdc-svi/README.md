# `cdc-svi/`

The [CDC/ATSDR Social Vulnerability Index](https://www.atsdr.cdc.gov/place-health/php/svi/) 2022 for the 50 states and DC, by census tract and by county. CDC builds it from the 2018–2022 American Community Survey. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/SVI_2022_US.csv`, `raw/SVI_2022_US_county.csv` | Tract (84,120 rows) and county (3,144 rows) tables without geometry |
| `raw/SVI_2022_US.zip`, `raw/SVI_2022_US_county.zip` | The same tables as File Geodatabases with polygons, EPSG:4269 |
| `raw/catalog.json` | STAC Collection `cdc-svi-raw` |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`; the files read directly (129 MB in total).

## Columns

`FIPS` is the 11-digit tract or 5-digit county GEOID and joins to `GEOID` in `tiger/`. `RPL_THEMES` is the overall percentile rank (0 to 1; higher is more vulnerable), and `RPL_THEME1` to `RPL_THEME4` are the ranks for socioeconomic status, household characteristics, racial and ethnic minority status, and housing type and transportation. `E_` columns are ACS estimates, `M_` margins of error, `EP_` percentages, `EPL_` per-variable percentile ranks and `F_` flags for the 90th percentile. `-999` marks missing values. CDC's [documentation](https://www.atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html) defines every column.

### Python

```python
import geopandas as gpd
import pandas as pd

raw = "/project/cowy/ascend-data-catalog/cdc-svi/raw"
county = pd.read_csv(f"{raw}/SVI_2022_US_county.csv", dtype={"FIPS": str})

# Tract polygons for one state. Columns named in `where` must also be in `columns`.
wy = gpd.read_file(f"zip://{raw}/SVI_2022_US.zip!SVI2022_US_tract.gdb",
                   where="ST_ABBR = 'WY'", columns=["ST_ABBR", "FIPS", "RPL_THEMES"])
```

### Julia

Packages: `CSV`, `DataFrames`, `ArchGDAL`.

```julia
using CSV, DataFrames, ArchGDAL

raw = "/project/cowy/ascend-data-catalog/cdc-svi/raw"
county = CSV.read("$raw/SVI_2022_US_county.csv", DataFrame; types = Dict(:FIPS => String))

# Tract polygons for one state; geometry is in the `Shape` column
wy = ArchGDAL.read("/vsizip/$raw/SVI_2022_US.zip/SVI2022_US_tract.gdb") do ds
    ArchGDAL.executesql(layer -> DataFrame(layer), ds, "SELECT FIPS, RPL_THEMES FROM SVI2022_US_tract WHERE ST_ABBR = 'WY'")
end
```

### R

On MedicineBow, load R and the cluster GDAL in every session with `module load arcc/1.0 gcc/15.2.0` then `module load r/4.5.3 gdal/3.13.0 geos/3.14.1 proj/9.7.0`. Install `terra` once into your own library, from source so that it links to the cluster GDAL:

```r
install.packages("terra", repos = "https://cloud.r-project.org")
```

```r
library(terra)

raw <- "/project/cowy/ascend-data-catalog/cdc-svi/raw"
county <- read.csv(paste0(raw, "/SVI_2022_US_county.csv"), colClasses = c(FIPS = "character"))

# Tract polygons for one state
wy <- vect(paste0("/vsizip/", raw, "/SVI_2022_US.zip/SVI2022_US_tract.gdb"),
           query = "SELECT FIPS, RPL_THEMES FROM SVI2022_US_tract WHERE ST_ABBR = 'WY'")
```

## Rebuilding

```sh
sbatch --job-name=cdc-svi-dl ../_shared/scripts/download_raw.sh cdc-svi   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                                  # STAC JSON for raw/; run by the owner of raw/
```
