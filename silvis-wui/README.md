# `silvis-wui/`

[The 1990–2020 wildland-urban interface of the conterminous United States](https://doi.org/10.2737/RDS-2015-0012-4) (4th edition), from the SILVIS Lab and the USDA Forest Service: WUI class, housing and vegetation by 2020 census block for 1990, 2000, 2010 and 2020. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/RDS-2015-0012-4.zip` | File Geodatabase `Data/CONUS_WUI_block_1990_2020_change_v4.gdb` as downloaded (5.0 GB, read-only) |
| `raw/catalog.json` | STAC Collection `silvis-wui-raw` |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`; the geodatabase reads directly from the zip.

## Columns

One layer, `CONUS_WUI_block_1990_2020_change_v4`: 9,158,401 MultiPolygons in NAD83 Albers (metres).

- **Keys:** `BLK20` (15-digit 2020 block GEOID), `fips` (5-digit county), `STATE` (two-letter code).
- **WUI:** `WUICLASS1990`, `WUICLASS2000`, `WUICLASS2010`, `WUICLASS2020` (for example `Low_Dens_Intermix`, `Med_Dens_Interface`, `Uninhabited_Veg`) and the matching `WUIFLAG<year>`.
- **Housing and population:** `HU<year>`, `HUDEN<year>` (units per km²); for 2020 also `POP2020`, `POPDEN2020`, `OCCHU2020`, `VACHU2020`.
- **Vegetation:** `VEG1992PC`, `VEG2001PC`, `VEG2011PC`, `VEG2019PC` (percent wildland vegetation from NLCD), `BUFVEG`.

### Python

```python
import geopandas as gpd

gdb = "zip:///project/cowy/ascend-data-catalog/silvis-wui/raw/RDS-2015-0012-4.zip!Data/CONUS_WUI_block_1990_2020_change_v4.gdb"

# Columns named in `where` must also be in `columns`.
teton = gpd.read_file(gdb, where="BLK20 LIKE '56039%'",
                      columns=["BLK20", "WUICLASS2020", "HU2020"])   # Teton County, WY: 1,540 blocks
```

An attribute filter scans all 9.2 million rows and takes about 40 s.

## Rebuilding

```sh
sbatch --job-name=silvis-wui-dl ../_shared/scripts/download_raw.sh silvis-wui   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                                        # STAC JSON for raw/; run by the owner of raw/
```
