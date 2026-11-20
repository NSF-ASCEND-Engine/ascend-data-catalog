# `wildfire-risk-to-communities/`

USDA Forest Service [Wildfire Risk to Communities](https://doi.org/10.2737/RDS-2020-0016-2), 2nd edition (RDS-2020-0016-2, published 2024): eight 30 m rasters of wildfire likelihood, intensity and risk to structures. Built from LANDFIRE 2020 (version 2.2.0) fuels and FSim burn probability; the FGDC metadata gives a ground-condition date of 2020-12-31. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/RDS-2020-0016-2_<layer>_CONUS.zip` | One zip per layer for CONUS (read-only) |
| `raw/RDS-2020-0016-2_Alaska.zip`, `raw/RDS-2020-0016-2_Hawaii.zip` | All eight layers for each state (read-only) |
| `raw/catalog.json` | STAC Collection `wildfire-risk-to-communities-raw`, one asset per zip |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`. The Archive's other per-state zips repeat the CONUS rasters and are not mirrored; their links are on the DOI landing page.

## Layers

| Code | Layer |
|---|---|
| `BP` | Annual burn probability |
| `CFL` | Conditional flame length (ft), given a fire |
| `FLEP4`, `FLEP8` | Probability that flame length exceeds 4 ft or 8 ft, given a fire |
| `RPS` | Risk to potential structures |
| `CRPS` | Conditional risk to potential structures, given a fire |
| `Exposure` | Exposure type: 0 not exposed, 1 directly exposed, values between for indirect exposure |
| `WHP` | Wildfire hazard potential |

A CONUS zip holds `<layer>_CONUS/<layer>_CONUS.tif` with its overviews (`.tif.ovr`) and FGDC metadata (`.tif.xml`). The rasters are EPSG:5070, 156335 × 101538, nodata -9999, stored as full-width strips.

Reading through the zip is slow: the GeoTIFFs are deflated inside the zip, so GDAL decompresses from the start of the file to reach a window. A window from `Exposure` (4.6 GB GeoTIFF) takes about 14 s, and the larger layers take longer. For repeated reads, unzip the GeoTIFF to `/gscratch` first.

### Python

```python
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

zip_path = "/project/cowy/ascend-data-catalog/wildfire-risk-to-communities/raw/RDS-2020-0016-2_Exposure_CONUS.zip"
with rasterio.open(f"zip://{zip_path}!Exposure_CONUS/Exposure_CONUS.tif") as src:
    box = transform_bounds("EPSG:4326", src.crs, -105.6, 39.9, -105.2, 40.2)   # lon/lat
    exposure = src.read(1, window=from_bounds(*box, src.transform), masked=True)
```

### Julia

Packages: `Rasters`, `ArchGDAL`, `Proj`.

```julia
using Rasters, ArchGDAL, Proj
import Rasters: X, Y, (..)

zipfile = "/project/cowy/ascend-data-catalog/wildfire-risk-to-communities/raw/RDS-2020-0016-2_Exposure_CONUS.zip"
r = Raster("/vsizip/$zipfile/Exposure_CONUS/Exposure_CONUS.tif"; lazy = true)

trans = Proj.Transformation("EPSG:4326", "EPSG:5070"; always_xy = true)
(x0, x1), (y0, y1) = Proj.bounds(trans, (-105.6, -105.2), (39.9, 40.2))    # lon/lat
exposure = read(r[X(x0 .. x1), Y(y0 .. y1)])
```

### R

On MedicineBow, load R and the cluster GDAL in every session with `module load arcc/1.0 gcc/15.2.0` then `module load r/4.5.3 gdal/3.13.0 geos/3.14.1 proj/9.7.0`. Install `terra` once into your own library, from source so that it links to the cluster GDAL:

```r
install.packages("terra", repos = "https://cloud.r-project.org")
```

```r
library(terra)

zipfile <- "/project/cowy/ascend-data-catalog/wildfire-risk-to-communities/raw/RDS-2020-0016-2_Exposure_CONUS.zip"
r <- rast(paste0("/vsizip/", zipfile, "/Exposure_CONUS/Exposure_CONUS.tif"))
box <- project(ext(-105.6, -105.2, 39.9, 40.2), "EPSG:4326", crs(r))    # lon/lat
exposure <- crop(r, box)
```

## Rebuilding

```sh
sbatch --job-name=wildfire-risk-to-communities-dl ../_shared/scripts/download_raw.sh wildfire-risk-to-communities
scripts/build_catalog.py        # STAC JSON for raw/; run by the owner of raw/
```
