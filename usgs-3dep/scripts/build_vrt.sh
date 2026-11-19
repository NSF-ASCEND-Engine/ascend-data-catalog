#!/bin/bash
# Build derived/USGS_Seamless_DEM_13.vrt: the USGS seamless VRT with each tile's
# /vsicurl S3 URL replaced by the local copy in raw/, so GDAL-based readers open
# all tiles as one raster without network access.
#
#   usgs-3dep/scripts/build_vrt.sh

set -euo pipefail

DS="/project/cowy/ascend-data-catalog/usgs-3dep"
mkdir -p "$DS/derived"
sed -E 's|relativeToVRT="0">/vsicurl/https://prd-tnm\.s3\.amazonaws\.com/StagedProducts/Elevation/13/TIFF/current/[^/]+/|relativeToVRT="1">../raw/|' \
    "$DS/raw/USGS_Seamless_DEM_13.vrt" > "$DS/derived/USGS_Seamless_DEM_13.vrt"

# Every tile the VRT names must be in raw/.
missing=$(grep -oE '\.\./raw/[^<]+' "$DS/derived/USGS_Seamless_DEM_13.vrt" | sort -u \
    | while read -r f; do [ -e "$DS/derived/$f" ] || echo "$f"; done)
[ -z "$missing" ] || { echo "missing tiles:"; echo "$missing"; exit 1; } >&2
echo "wrote $DS/derived/USGS_Seamless_DEM_13.vrt"
