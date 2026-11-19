#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.10"]
# ///
"""Build the STAC Collection of wildfire-risk-to-communities.

    wildfire-risk-to-communities/scripts/build_catalog.py
"""

import sys
from pathlib import Path

import pystac

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent / "_shared/scripts"))
from stac_raw import raw_collection, save  # noqa: E402

DOI = "https://doi.org/10.2737/RDS-2020-0016-2"
LAYERS = {
    "BP": "Burn probability", "CFL": "Conditional flame length",
    "CRPS": "Conditional risk to potential structures", "Exposure": "Exposure type",
    "FLEP4": "Flame length exceedance probability, 4 ft",
    "FLEP8": "Flame length exceedance probability, 8 ft",
    "RPS": "Risk to potential structures", "WHP": "Wildfire hazard potential",
}


def layer(path: Path) -> dict:
    """Title an asset: RDS-2020-0016-2_<layer>_CONUS.zip is one layer, RDS-2020-0016-2_<State>.zip all eight."""
    name = path.stem.removeprefix("RDS-2020-0016-2_")
    if name.endswith("_CONUS"):
        return {"title": f"{LAYERS[name.removesuffix('_CONUS')]}, CONUS"}
    return {"title": f"All eight layers, {name}"}


if __name__ == "__main__":
    raw = raw_collection(
        SOURCE,
        id="wildfire-risk-to-communities-raw",
        title="Wildfire Risk to Communities, 2nd edition (raw)",
        description="USDA Forest Service Wildfire Risk to Communities landscape-wide risk components "
                    "(RDS-2020-0016-2, published 2024) as downloaded by `_shared/scripts/download_raw.sh "
                    "wildfire-risk-to-communities` from the Forest Service Research Data Archive. "
                    "Eight 30 m GeoTIFF layers: " + "; ".join(f"{k} ({v.lower()})" for k, v in LAYERS.items())
                    + ". One zip per layer for CONUS, plus one zip each for Alaska and Hawaii holding "
                    "all eight layers. The Archive's other per-state zips repeat the CONUS rasters and "
                    "are not mirrored; their URLs are on the DOI landing page. Built from "
                    "LANDFIRE 2020 (version 2.2.0) fuels and FSim burn probability; the FGDC metadata "
                    "gives a ground-condition date of 2020-12-31. Read-only.",
        bbox=[-179.15, 18.9, 179.78, 71.4],
        interval=("2020-12-31", "2020-12-31"),
        license_url=DOI,
        license_title="Wildfire Risk to Communities: Spatial datasets of landscape-wide wildfire risk "
                      "components for the United States (2nd Edition)",
        asset_fields=layer,
        keywords=["wildfire", "risk", "burn probability", "flame length", "wildfire hazard potential"],
        providers=[pystac.Provider("USDA Forest Service, Rocky Mountain Research Station", url=DOI,
                                   roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR,
                                          pystac.ProviderRole.HOST])],
    )
    save(SOURCE, raw)
