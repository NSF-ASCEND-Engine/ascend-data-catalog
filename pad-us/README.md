# `pad-us/`

The USGS [Protected Areas Database of the United States (PAD-US) 4.1](https://doi.org/10.5066/P96WBCHS): polygons of public and protected lands with owner, manager, designation, GAP status and public access. Covers the 50 states, DC, territories and marine areas. Owner: joshday.

| Path | Contents |
|---|---|
| `raw/PADUS4_1Geodatabase.zip` | National File Geodatabase as downloaded (1.5 GB, read-only) |
| `raw/PADUS41_MetadataXML_FGDC.xml`, `raw/VersHist_PADUS.txt` | FGDC metadata with attribute definitions; version history |
| `raw/catalog.json` | STAC Collection `pad-us-raw` |
| `scripts/` | `urls.txt` and the code that writes the STAC JSON |

There is no `derived/`; the geodatabase reads directly from the zip.

## Layers

All layers are MultiPolygon in USA Contiguous Albers Equal Area Conic USGS (ESRI:102039, metres).

| Layer | Rows | Contents |
|---|---|---|
| `PADUS4_1Fee` | 296,456 | Land owned outright by an agency or organization; the layer for land ownership |
| `PADUS4_1Easement` | 341,954 | Conservation easements |
| `PADUS4_1Designation` | 13,398 | Management designations, which overlap Fee |
| `PADUS4_1Proclamation` | 3,439 | Congressional or administrative proclamation boundaries, which include inholdings |
| `PADUS4_1Marine` | 1,739 | Marine protected areas |
| `PADUS4_1Combined_Proclamation_Marine_Fee_Designation_Easement` | 656,986 | All five; polygons overlap, so do not sum areas |

Common attributes: `Mang_Name` and `Mang_Type` (manager), `Own_Name` and `Own_Type` (owner), `Des_Tp` (designation type), `GAP_Sts` (1 to 4), `Pub_Access`, `Unit_Nm`, `State_Nm` (two-letter code), `GIS_Acres`, `Src_Date`. The geodatabase's lookup tables (`Agency_Name`, `Designation_Type`, `GAP_Status`, …) decode the coded values.

### Python

```python
import geopandas as gpd

gdb = "zip:///project/cowy/ascend-data-catalog/pad-us/raw/PADUS4_1Geodatabase.zip!PADUS4_1Geodatabase.gdb"

# Columns named in `where` must also be in `columns`. About 3 s for one state.
wy = gpd.read_file(gdb, layer="PADUS4_1Fee", where="State_Nm = 'WY'",
                   columns=["State_Nm", "Mang_Name", "Des_Tp", "GAP_Sts", "Pub_Access", "Unit_Nm", "GIS_Acres"])
```

## Rebuilding

```sh
sbatch --job-name=pad-us-dl ../_shared/scripts/download_raw.sh pad-us   # urls.txt → raw/; skips files already present
scripts/build_catalog.py                                                # STAC JSON for raw/; run by the owner of raw/
```
