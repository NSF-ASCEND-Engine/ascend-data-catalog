# AGENTS.md

STAC catalog, build scripts and documentation for the datasets in `/project/cowy/ascend-data-catalog` on MedicineBow. Git tracks only text; the data stay on the cluster. `README.md` describes the layout and STAC terms.

## Rules

- `<source>/raw/` holds unmodified vendor files and is read-only. Do not edit, rename or delete anything in it. Build new products in `<source>/derived/`.
- Do not hand-edit STAC JSON (`catalog.json`, `raw.json`, `derived.json`, `<source>/**/*.json`). Change `<source>/scripts/build_catalog.py` and rerun it; it validates before writing.
- `.gitignore` ignores everything except READMEs, STAC JSON, `<source>/scripts/`, `_quarto.yml` and the workflow. Never commit data files.
- Run downloads and builds through Slurm (`--account=cowy-firesurro`), not on the login node. Use `/lscratch` or `/gscratch` for intermediates.
- Every source is shared with all ASCEND performers. Do not add data whose license or owner does not permit that.

## Adding a source

1. Create `<source>/scripts/urls.txt` with one `URL [filename]` per line.
2. `sbatch --job-name=<source>-dl _shared/scripts/download_raw.sh <source>` fetches it into `<source>/raw/`.
3. Copy a `build_catalog.py` from an existing source (`tiger/` is the smallest), set the Collection metadata, and run it. It links the source from `raw.json`.
4. Write `<source>/README.md`: what the data are, a path table, and a read example that has been run against the files.

Scripts are `uv` scripts with inline dependencies; `uv` is at `~/.local/bin`.

## Website

`.github/workflows/publish.yml` publishes https://nsf-ascend-engine.github.io/ascend-data-catalog/ on every push to `main`. The pages are generated from the STAC JSON and READMEs by `_shared/scripts/build_site.py`, so a new source appears once its JSON and README are committed. To preview: `python3 _shared/scripts/build_site.py && quarto preview`, in a clone without the data.
