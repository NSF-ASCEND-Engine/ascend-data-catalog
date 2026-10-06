#!/bin/bash
# Build derived/usa_structures.parquet from raw/ on one MedicineBow CPU node.
#
#   sbatch build_geoparquet.sh
#   sbatch --dependency=afterok:<download job id> build_geoparquet.sh
#
# Sizing comes from a test on WY + CO (2.9M structures): CO's 0.44 GB zip took
# 57 s and peaked at 4.3 GB RSS. Memory scales with the state, so Texas
# (2.4 GB zip) should need ~25 GB; with the largest states running at once,
# 8 workers fit comfortably in 192 GB.

#SBATCH --job-name=usa-structures-parquet
#SBATCH --account=cowy-firesurro
#SBATCH --partition=mb
#SBATCH --qos=fast
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=192G
#SBATCH --output=%x-%j.out

set -euo pipefail

DS="/project/cowy/data/fema-usa-structures"
OUT="${OUT:-$DS/derived/usa_structures.parquet}"
export PATH="$HOME/.local/bin:$PATH"   # uv

# Per-state intermediates go on node-local disk, not /project.
SCRATCH="/lscratch/$USER/${SLURM_JOB_ID:-$$}"
mkdir -p "$SCRATCH"
trap 'rm -rf "$SCRATCH"' EXIT

export OMP_NUM_THREADS=1

echo "[$(date)] ${SLURM_JOB_ID:-local} on $(hostname)"
"$DS/scripts/build_geoparquet.py" \
    --raw "$DS/raw" \
    --out "$OUT" \
    --scratch "$SCRATCH" \
    --workers "${SLURM_CPUS_PER_TASK:-8}"
echo "[$(date)] done"
