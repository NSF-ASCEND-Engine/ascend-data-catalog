#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of silvis-wui.

    silvis-wui/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

DOI = "https://doi.org/10.2737/RDS-2015-0012-4"

if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="silvis-wui-raw",
        title="SILVIS wildland-urban interface 1990-2020 (raw)",
        description="The 1990-2020 wildland-urban interface of the conterminous United States "
                    "(RDS-2015-0012-4, 4th edition), produced by the SILVIS Lab and the USDA Forest "
                    "Service, as downloaded by `_shared/scripts/download_raw.sh silvis-wui` from the "
                    "Forest Service Research Data Archive. One zip holding the File Geodatabase "
                    "`CONUS_WUI_block_1990_2020_change_v4.gdb`: 9,158,401 2020 census-block polygons in "
                    "NAD83 Albers with WUI class, housing units, housing density and vegetation cover "
                    "for 1990, 2000, 2010 and 2020. Read-only.",
        bbox=[-124.85, 24.4, -66.88, 49.4],
        interval=("1990-01-01", "2020-12-31"),
        license_url=DOI,
        license_title="The 1990-2020 wildland-urban interface of the conterminous United States",
        keywords=["wildland-urban interface", "WUI", "housing density", "census blocks", "wildfire"],
        providers=[
            pystac.Provider("SILVIS Lab, University of Wisconsin-Madison", roles=[pystac.ProviderRole.PRODUCER],
                            url="https://silvis.forest.wisc.edu/data/wui-change/"),
            pystac.Provider("USDA Forest Service", url=DOI,
                            roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                                   pystac.ProviderRole.HOST]),
        ],
    )
    save(SOURCE, raw)
