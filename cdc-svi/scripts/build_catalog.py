#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of cdc-svi/raw.

    cdc-svi/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="cdc-svi-raw",
        title="CDC/ATSDR Social Vulnerability Index 2022 (raw)",
        description="CDC/ATSDR Social Vulnerability Index 2022 for the 50 states and DC as downloaded "
                    "by `_shared/scripts/download_raw.sh cdc-svi` from the URLs in `scripts/urls.txt`: "
                    "census-tract and county tables, each as a CSV and as a File Geodatabase zip with "
                    "geometry. Built by CDC from the 2018-2022 American Community Survey. Read-only.",
        bbox=[-179.15, 18.9, 179.78, 71.4],
        interval=("2018-01-01", "2022-12-31"),
        license_url="https://www.atsdr.cdc.gov/place-health/php/svi/",
        license_title="CDC/ATSDR Social Vulnerability Index",
        keywords=["social vulnerability", "SVI", "census tracts", "counties", "demographics"],
        providers=[pystac.Provider("CDC/ATSDR", url="https://www.atsdr.cdc.gov/place-health/php/svi/",
                                   roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                                          pystac.ProviderRole.HOST])],
    )
    save(SOURCE, raw)
