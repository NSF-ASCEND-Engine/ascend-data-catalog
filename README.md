# `ascend-data-catalog`

Shared datasets for NSF ASCEND Engine performers, at `/project/cowy/ascend-data-catalog` on MedicineBow. Personal work stays in `/project/cowy/<user>/`.

## Adding Sources

- ASCEND Engine performers are welcome to add their own sources.
  - Note that all sources are shared across all performers.
  - Reach out to `josh@rallypoint1.com` for assistance. 

## Layout

- **`<source>/raw/`** unmodified vendor files as downloaded.
- **`<source>/derived/`** products built from `raw/` and other sources.
- **`<source>/scripts/`** code that builds `derived/`, examples, etc.
- **`_shared/scripts/`** code used by several sources: `download_raw.sh` fetches a source's `scripts/urls.txt` into its `raw/`, and `stac_raw.py` writes the STAC JSON for a `raw/` directory. A source whose raw files read directly has no `derived/`.

## STAC Catalog

- **`catalog.json`** (root) has two children:
  - **`raw.json`**, links to every `<source>/raw/catalog.json`
  - **`derived.json`**: links to every `<source>/derived/catalog.json`

A standard template is as follows:

```
ascend-data-catalog/
    catalog.json                        # Catalog (ascend-data-catalog root)
    raw.json                            # Catalog of every <source>/raw/catalog.json
    derived.json                        # Catalog of every <source>/derived/catalog.json
    <source>/
        derived/
            catalog.json                # Catalog of this <source>'s derived products
            derived-dataset.zarr        # a data product 
            derived-dataset.json        # Collection for data product
        raw/                            # Untouched original datasets
            catalog.json                # Collection with one asset per raw file
        scripts/
            build_catalog.py            # Writes this <source>'s STAC JSON
            build-derived-dataset.zarr  # For reproducibility
        README.md                       # Explains what the data is and how to use it
```

### STAC Terms 

| Term | Meaning |
|---|---|
| **Catalog** | A JSON file that groups other Catalogs and Collections through `links`. |
| **Collection** | A Catalog that describes one dataset: extent (bbox + time range), license, providers, keywords, and fields shared by everything in it. |
| **Item** | One spatiotemporal unit, such as a single scene or tile, as a GeoJSON Feature with its own geometry and datetime. Used when a dataset is many separate files. |
| **Asset** | A link (`href`) to an actual data file or store, with a media `type` and `roles`. Assets belong to an Item or directly to a Collection. |
| **Link** | A typed pointer between STAC files: `root`, `parent`, `child`, `item`, `license`. |
| **Extension** | A published schema that adds namespaced fields, listed in `stac_extensions`. |
