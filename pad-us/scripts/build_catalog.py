#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of pad-us.

    pad-us/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

DOI = "https://doi.org/10.5066/P96WBCHS"

if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="pad-us-raw",
        title="PAD-US 4.1 (raw)",
        description="USGS Gap Analysis Project Protected Areas Database of the United States (PAD-US) "
                    "4.1 full inventory as downloaded by `_shared/scripts/download_raw.sh pad-us` from "
                    "ScienceBase: the national File Geodatabase zip, its FGDC metadata and the version "
                    "history. The geodatabase has six polygon feature classes (Fee, Easement, "
                    "Designation, Proclamation, Marine, and all five combined) in USA Contiguous Albers "
                    "Equal Area Conic USGS (ESRI:102039), with owner, manager, designation type, GAP "
                    "status and public access attributes, plus lookup tables for the coded attributes. "
                    "Covers the 50 states, DC, territories and marine areas. Source dates vary by "
                    "record (`Src_Date`); the interval's end is the geodatabase's packaging date. "
                    "Read-only.",
        bbox=[-180.0, -15.0, 180.0, 72.0],
        interval=(None, "2025-03-30"),
        license_url=DOI,
        license_title="PAD-US 4.1 data release",
        keywords=["protected areas", "land ownership", "land management", "PAD-US", "GAP status"],
        providers=[pystac.Provider("U.S. Geological Survey Gap Analysis Project", url=DOI,
                                   roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                                          pystac.ProviderRole.HOST])],
    )
    save(SOURCE, raw)
