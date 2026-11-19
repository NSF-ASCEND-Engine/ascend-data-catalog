#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of camels.

    camels/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

DOI = "https://doi.org/10.5281/zenodo.15529996"

if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="camels-raw",
        title="CAMELS (raw)",
        description="CAMELS (Catchment Attributes and MEteorology for Large-sample Studies) as "
                    "downloaded by `_shared/scripts/download_raw.sh camels` from Zenodo record "
                    "15529996: time series v1.2 and catchment attributes v2.0 for 671 minimally "
                    "disturbed CONUS basins of the USGS HCDN-2009 network. "
                    "`basin_timeseries_v1p2_metForcing_obsFlow.zip` holds daily basin-mean forcings "
                    "from Daymet and NLDAS (1980-2014) and Maurer (1980-2008), observed USGS "
                    "streamflow, basin metadata and simplified basin shapefiles; the three "
                    "`modelOutput` zips hold SNOW-17 / SAC-SMA simulations per forcing; "
                    "`basin_set_full_res.zip` holds full-resolution basin boundaries; the "
                    "`camels_*.txt` files are semicolon-delimited attribute tables keyed by `gauge_id`. "
                    "Read-only.",
        bbox=[-124.85, 24.4, -66.88, 49.4],
        interval=("1980-01-01", "2014-12-31"),
        license="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_title="Creative Commons Attribution 4.0 International",
        keywords=["hydrology", "streamflow", "catchments", "CAMELS", "forcing", "large-sample"],
        providers=[
            pystac.Provider("NSF National Center for Atmospheric Research", url="https://ral.ucar.edu/solutions/products/camels",
                            roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR]),
            pystac.Provider("Zenodo", roles=[pystac.ProviderRole.HOST], url=DOI),
        ],
    )
    raw.add_link(pystac.Link("cite-as", DOI))
    save(SOURCE, raw)
