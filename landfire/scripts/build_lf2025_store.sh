#!/bin/bash
# Build the LF2025 fuels + LF2020 terrain Zarr store on one MedicineBow CPU node.
#
#   sbatch build_lf2025_store.sh
#
# Override any of SRC, OUT, VENV or LF_EXTRA_ARGS from the environment, e.g.
#   OUT=/gscratch/$USER/test.zarr LF_EXTRA_ARGS="--limit 2 --grid all" sbatch build_lf2025_store.sh
#
# The converter marks each array complete as it finishes, so a preempted or
# requeued job resumes at the next unfinished layer rather than starting over.
#
# Sizing comes from job 18106574 on mbcpu-010 with these settings: Elev, the
# largest layer, took 38 s (20 s to extract 6.8 GB, 17 s to write 15.9 Gpx);
# CBD took 11 s and EVT 17 s. All 23 layers should land near 10 minutes, so the
# two-hour request is margin, not an estimate. Peak RSS was 38 GB.

#SBATCH --job-name=landfire-zarr
#SBATCH --account=cowy-firesurro
#SBATCH --partition=mb
#SBATCH --qos=fast
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --output=%x-%j.out
#SBATCH --requeue
#SBATCH --open-mode=append

set -euo pipefail

LF="/project/cowy/ascend-data-catalog/landfire"
SRC="${SRC:-$LF/raw}"
OUT="${OUT:-$LF/derived/lf2025_fuels_terrain.zarr}"
VENV="${VENV:-$LF/scripts/.venv}"
export PATH="$HOME/.local/bin:$PATH"   # uv

# Extracted GeoTIFFs go on node-local disk (up to ~9 GB for Elev), not /project.
if [ -n "${SLURM_JOB_ID:-}" ]; then
    SCRATCH="/lscratch/$USER/$SLURM_JOB_ID/landfire"
else
    SCRATCH="${TMPDIR:-/tmp}/landfire-$$"
fi
mkdir -p "$SCRATCH" "$(dirname "$OUT")"
trap 'rm -rf "$SCRATCH"' EXIT

# Idempotent, so a requeued run reuses the environment instead of rebuilding it.
if [ ! -x "$VENV/bin/python" ]; then
    echo "[$(date)] building $VENV"
    uv venv --python 3.12 "$VENV"
    uv pip install --python "$VENV/bin/python" 'rasterio>=1.4' 'zarr>=3' numcodecs
fi

# GDAL sizes its block cache from total node RAM, which is ~50 GB per process on
# a 1 TB node. Pin it -- each block is read once, so a large cache buys nothing --
# and keep every library single-threaded so the process pool is the only source
# of parallelism.
export GDAL_CACHEMAX=256
export GDAL_NUM_THREADS=1
export OMP_NUM_THREADS=1
export BLOSC_NTHREADS=1

CPUS="${SLURM_CPUS_PER_TASK:-8}"
echo "[$(date)] $SLURM_JOB_ID on $(hostname), $CPUS workers, scratch $SCRATCH"

# LF_EXTRA_ARGS is deliberately unquoted so it can carry several flags.
# shellcheck disable=SC2086
"$VENV/bin/python" "$LF/scripts/landfire_to_zarr.py" \
    --src "$SRC" \
    --out "$OUT" \
    --release LF2025 --release LF2020 --short-names \
    --exclude 'LF2020_Dist*' --exclude 'LF2020_BPS*' \
    --chunk 1024 1024 \
    --workers "$CPUS" \
    --scratch "$SCRATCH" \
    --progress 60 \
    ${LF_EXTRA_ARGS:-}

echo "[$(date)] done"
du -sh "$OUT"
