#!/bin/bash
# Download every file listed in <source>/scripts/urls.txt into <source>/raw/.
#
#   sbatch --job-name=<source>-dl /project/cowy/ascend-data-catalog/_shared/scripts/download_raw.sh <source>
#
# Each line of urls.txt is "URL [filename]"; the filename defaults to the URL's
# basename and is needed where the URL does not end in one (Box, ScienceBase,
# Zenodo). Files already in raw/ are skipped, so a rerun only fetches what is
# missing. A download lands in raw/ only after curl reports a complete transfer
# and, for a zip, after `unzip -t` passes. raw/ is made read-only at the end.

#SBATCH --account=cowy-firesurro
#SBATCH --partition=mb
#SBATCH --qos=fast
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=4G
#SBATCH --output=%x-%j.out

set -euo pipefail

DS="/project/cowy/ascend-data-catalog/$1"
export RAW="$DS/raw"
URLS="$DS/scripts/urls.txt"
JOBS="${SLURM_CPUS_PER_TASK:-8}"

mkdir -p "$RAW"
chmod -R u+w "$RAW"

fetch() {
    local url=$1 dest=$RAW/${2:-$(basename "$1")}
    if [ -e "$dest" ]; then
        echo "skip $(basename "$dest")"
        return
    fi
    # Box and fs.usda.gov reject curl's default user agent.
    curl -sfL --retry 5 --retry-delay 10 -A "Mozilla/5.0 (compatible; curl)" -o "$dest.part" "$url" \
        || { echo "FAIL $(basename "$dest")" >&2; return 1; }
    case "$dest" in *.zip) unzip -tqq "$dest.part" >/dev/null ;; esac
    mv "$dest.part" "$dest"
    echo "ok   $(basename "$dest") $(stat -c %s "$dest")"
}
export -f fetch

echo "[$(date)] ${SLURM_JOB_ID:-local} on $(hostname), $JOBS parallel downloads"
xargs -P "$JOBS" -L 1 bash -c 'fetch "$@"' _ < "$URLS" || true

n=$(find "$RAW" -type f ! -name catalog.json ! -name '*.part' | wc -l)
echo "[$(date)] $n of $(wc -l < "$URLS") files in $RAW ($(du -sh "$RAW" | cut -f1))"
[ "$n" -eq "$(wc -l < "$URLS")" ]
chmod -R a-w "$RAW"
