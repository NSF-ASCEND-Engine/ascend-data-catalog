#!/bin/bash
# Download every USA Structures state/territory zip listed in urls.txt into raw/.
#
#   sbatch download_raw.sh
#
# urls.txt holds the 56 links (50 states, DC, 5 territories) on FEMA's
# "USA Structures Data" hub page as of 2026-10-05. To refresh it:
#
#   curl -sL "https://www.arcgis.com/sharing/rest/content/items/8388995e228e4e30a882686ac3ab256e/data?f=json" \
#       | grep -oE 'https://fema-femadata[^"\\ )]+\.zip' | sort -u > urls.txt
#
# Files already present at the server's Content-Length are skipped, so a rerun
# only fetches what is missing or incomplete. raw/ is made read-only at the end.

#SBATCH --job-name=usa-structures-dl
#SBATCH --account=cowy-firesurro
#SBATCH --partition=mb
#SBATCH --qos=fast
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=4G
#SBATCH --output=%x-%j.out

set -euo pipefail

DS="/project/cowy/ascend-data-catalog/fema-usa-structures"
RAW="${RAW:-$DS/raw}"
URLS="${URLS:-$DS/scripts/urls.txt}"
JOBS="${SLURM_CPUS_PER_TASK:-8}"

chmod u+w "$RAW"

fetch() {
    local url=$1 dest=$2/$(basename "$1")
    local want have
    want=$(curl -sfIL "$url" | awk 'tolower($1)=="content-length:"{n=$2} END{print n+0}')
    have=$(stat -c %s "$dest" 2>/dev/null || echo 0)
    if [ "$have" -eq "$want" ] && [ "$want" -gt 0 ]; then
        echo "skip $(basename "$dest")"
        return
    fi
    curl -sfL --retry 5 --retry-delay 10 -o "$dest.part" "$url"
    have=$(stat -c %s "$dest.part")
    if [ "$have" -ne "$want" ]; then
        echo "FAIL $(basename "$dest"): got $have bytes, expected $want" >&2
        return 1
    fi
    unzip -tqq "$dest.part" >/dev/null
    mv "$dest.part" "$dest"
    echo "ok   $(basename "$dest") $have"
}
export -f fetch

echo "[$(date)] ${SLURM_JOB_ID:-local} on $(hostname), $JOBS parallel downloads"
xargs -P "$JOBS" -I{} bash -c 'fetch "$1" "$2"' _ {} "$RAW" < "$URLS"

n=$(ls "$RAW"/*.zip | wc -l)
echo "[$(date)] $n zips in $RAW ($(du -sh "$RAW" | cut -f1))"
[ "$n" -eq "$(wc -l < "$URLS")" ]
chmod a-w "$RAW"/*.zip "$RAW"
