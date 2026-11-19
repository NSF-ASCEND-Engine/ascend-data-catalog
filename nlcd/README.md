# `nlcd/`

USGS [Annual National Land Cover Database](https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database) Collection 1.1: yearly CONUS land cover and fractional impervious surface at 30 m, 1985–2024, as the data bundles distributed at [mrlc.gov](https://www.mrlc.gov/data). Owner: joshday.

| Path | Contents |
|---|---|
| `raw/Annual_NLCD_LndCov_<year>_CU_C1V1.zip` | Land cover, 40 zips of about 1.4 GB (read-only) |
| `raw/Annual_NLCD_FctImp_<year>_CU_C1V1.zip` | Fractional impervious surface (percent), 40 zips of about 0.9 GB (read-only) |
| `raw/catalog.json` | STAC Collection `nlcd-raw`, one asset per zip |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`. Each zip holds one GeoTIFF with the zip's name, its FGDC metadata and a `.tif.aux.xml`. The GeoTIFF is uint8, 160000 × 105000, 512 × 512 deflate blocks, nodata 250, in Albers Equal Area on WGS 84. That grid is not LANDFIRE's EPSG:5070 (NAD83) grid, so the two need resampling to combine.

Land cover values are the NLCD classes: 11 open water, 12 perennial ice/snow, 21–24 developed (open space, low, medium, high intensity), 31 barren, 41–43 deciduous, evergreen and mixed forest, 52 shrub/scrub, 71 grassland/herbaceous, 81 pasture/hay, 82 cultivated crops, 90 woody wetlands, 95 emergent herbaceous wetlands.

The other four Annual NLCD products (`LndChg`, `LndCnf`, `ImpDsc`, `SpcChg`) are not mirrored; they use the same URL pattern as `scripts/urls.txt`. `LndCnf` is about 7.8 GB per year.

### Python

```python
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

name = "Annual_NLCD_LndCov_2024_CU_C1V1"
with rasterio.open(f"zip:///project/cowy/ascend-data-catalog/nlcd/raw/{name}.zip!{name}.tif") as src:
    box = transform_bounds("EPSG:4326", src.crs, -105.6, 39.9, -105.2, 40.2)   # lon/lat
    cover = src.read(1, window=from_bounds(*box, src.transform))
```

A windowed read through the zip takes about 3 s. For many reads of one year, unzip that GeoTIFF to `/gscratch` first.

## Rebuilding

```sh
sbatch --job-name=nlcd-dl ../_shared/scripts/download_raw.sh nlcd   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                            # STAC JSON for raw/; run by the owner of raw/
```
