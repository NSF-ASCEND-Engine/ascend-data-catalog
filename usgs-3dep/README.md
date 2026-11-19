# `usgs-3dep/`

The USGS [3D Elevation Program](https://www.usgs.gov/3d-elevation-program) seamless 1/3 arc-second (about 10 m) DEM, as the 1 × 1 degree GeoTIFF tiles USGS distributes and as one VRT mosaic. Covers CONUS, Hawaii, the territories and the parts of Alaska with 1/3 arc-second data. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/USGS_13_<tile>.tif` | 1,449 tiles as downloaded (494 GB, read-only): float32 metres, EPSG:4269, 10812 × 10812, nodata -999999, LZW, 256 × 256 blocks |
| `raw/USGS_Seamless_DEM_13.vrt` | The USGS VRT, which reads the tiles from S3 |
| `raw/catalog.json` | STAC Collection `usgs-3dep-raw`, one asset per tile with its `proj:bbox` |
| `derived/USGS_Seamless_DEM_13.vrt` | The same VRT pointing at the tiles in `raw/` (3,888,006 × 939,612) |
| `derived/USGS_Seamless_DEM_13.json` | STAC Collection `usgs-3dep-13-vrt` |
| `derived/catalog.json` | STAC Catalog `usgs-3dep-derived` |
| `scripts/` | `urls.txt`, the VRT builder and the code that writes the STAC JSON |

A tile is named by its north-west corner: `USGS_13_n41w106.tif` covers 40–41° N, 106–105° W, plus a 6-pixel overlap on each side. Elevations are NAVD88 in CONUS. Source survey dates vary by tile. LANDFIRE's 30 m terrain layers (`landfire/derived`) are the alternative when the EPSG:5070 fuels grid is wanted.

### Python

```python
import rasterio
from rasterio.windows import from_bounds

with rasterio.open("/project/cowy/ascend-data-catalog/usgs-3dep/derived/USGS_Seamless_DEM_13.vrt") as src:
    window = from_bounds(-105.6, 39.9, -105.2, 40.2, src.transform)     # lon/lat
    elev = src.read(1, window=window, masked=True)
```

## Rebuilding

```sh
sbatch --job-name=usgs-3dep-dl ../_shared/scripts/download_raw.sh usgs-3dep   # urls.txt → raw/; skips files already present
scripts/build_vrt.sh                                                          # raw/ → derived/USGS_Seamless_DEM_13.vrt
scripts/build_catalog.py                                                      # STAC JSON for raw/ and derived/; run by the owner of raw/
```

`scripts/urls.txt` is the listing of `StagedProducts/Elevation/13/TIFF/current/*/*.tif` in the `prd-tnm` S3 bucket on 2026-11-19, plus the VRT.
