# `camels/`

[CAMELS](https://doi.org/10.5281/zenodo.15529996) (Catchment Attributes and MEteorology for Large-sample Studies): daily forcings, observed streamflow, model simulations and catchment attributes for 671 minimally disturbed CONUS basins of the USGS HCDN-2009 network, 1980–2014. Time series v1.2, attributes v2.0. License: CC-BY-4.0. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/basin_timeseries_v1p2_metForcing_obsFlow.zip` | Daily basin-mean forcings from Daymet and NLDAS (1980–2014) and Maurer (1980–2008), observed USGS streamflow, basin metadata, simplified basin shapefiles (3.4 GB) |
| `raw/basin_timeseries_v1p2_modelOutput_{daymet,maurer,nldas}.zip` | SNOW-17 / SAC-SMA simulations for each forcing (3.1–4.2 GB each) |
| `raw/basin_set_full_res.zip` | Full-resolution basin boundaries, `HCDN_nhru_final_671.shp` |
| `raw/camels_{name,topo,clim,hydro,soil,vege,geol}.txt` | Semicolon-delimited attribute tables, one row per basin, keyed by `gauge_id` |
| `raw/camels_attributes_v2.0.pdf`, `.xlsx`, `raw/readme.txt` | Attribute definitions, version history, citation |
| `raw/catalog.json` | STAC Collection `camels-raw` |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`. All files total 14.6 GB and are read-only.

`gauge_id` is the 8-digit USGS site number with leading zeros, so read it as a string. By gauge coordinates, 15 basins are gauged in Colorado and 15 in Wyoming. The basin set excludes regulated and urbanized catchments and ends in 2014.

### Python

```python
import geopandas as gpd
import pandas as pd

raw = "/project/cowy/ascend-data-catalog/camels/raw"
read = lambda name: pd.read_csv(f"{raw}/camels_{name}.txt", sep=";", dtype={"gauge_id": str})
attrs = read("name").merge(read("topo"), on="gauge_id").merge(read("hydro"), on="gauge_id")
basins = gpd.read_file(f"{raw}/basin_set_full_res.zip")
```

### Julia

Packages: `CSV`, `DataFrames`, `GeoDataFrames`.

```julia
using CSV, DataFrames, GeoDataFrames

raw = "/project/cowy/ascend-data-catalog/camels/raw"
tbl(name) = CSV.read("$raw/camels_$name.txt", DataFrame; delim = ';', types = Dict(:gauge_id => String))
attrs = innerjoin(tbl("name"), tbl("topo"), tbl("hydro"); on = :gauge_id)
basins = GeoDataFrames.read("/vsizip/$raw/basin_set_full_res.zip")
```

### R

On MedicineBow, load R and the cluster GDAL in every session with `module load arcc/1.0 gcc/15.2.0` then `module load r/4.5.3 gdal/3.13.0 geos/3.14.1 proj/9.7.0`. Install `terra` once into your own library, from source so that it links to the cluster GDAL:

```r
install.packages("terra", repos = "https://cloud.r-project.org")
```

```r
library(terra)

raw <- "/project/cowy/ascend-data-catalog/camels/raw"
tbl <- function(name) read.csv(sprintf("%s/camels_%s.txt", raw, name), sep = ";",
                               colClasses = c(gauge_id = "character"))
attrs <- Reduce(function(a, b) merge(a, b, by = "gauge_id"), lapply(c("name", "topo", "hydro"), tbl))
basins <- vect(paste0("/vsizip/", raw, "/basin_set_full_res.zip"))
```

## Citation

- Time series: Newman et al. (2015), doi:10.5194/hess-19-209-2015.
- Attributes: Addor et al. (2017), doi:10.5194/hess-2017-169.

## Rebuilding

```sh
sbatch --job-name=camels-dl ../_shared/scripts/download_raw.sh camels   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                                # STAC JSON for raw/; run by the owner of raw/
```
