#!/usr/bin/env python3
"""Write the Quarto website's pages from the STAC JSON and the READMEs.

    python3 _shared/scripts/build_site.py && quarto render

Writes, at the repository root (none of it is tracked):

    index.md                one table row and one summary per source
    datasets/<source>.md    the source's STAC summary followed by its README
    layout.md               the root README

Uses only the standard library and reads only tracked files, so it runs in CI
without the data.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "https://github.com/NSF-ASCEND-Engine/ascend-data-catalog"
PATH = "/project/cowy/ascend-data-catalog"


def load(path):
    return json.loads(path.read_text())


def children(path):
    """The STAC objects linked as `child` from the Catalog at ``path``, with their paths."""
    return [(p, load(p)) for p in ((path.parent / l["href"]).resolve() for l in load(path)["links"] if l["rel"] == "child")]


def year(stamp):
    return stamp[:4] if stamp else ""


def period(collection):
    start, end = map(year, collection["extent"]["temporal"]["interval"][0])
    if not start:
        return f"through {end}"
    return start if start == end else f"{start}–{end}"


def size(collection):
    """Total of the assets' `file:size`, or an empty string where none is recorded (a Zarr store)."""
    total = sum(a.get("file:size", 0) for a in collection.get("assets", {}).values())
    return f"{total / 1e9:,.1f} GB" if total >= 1e8 else f"{total / 1e6:,.0f} MB" if total else ""


def bbox(collection):
    west, south, east, north = collection["extent"]["spatial"]["bbox"][0]
    return f"{west:g}, {south:g}, {east:g}, {north:g}"


def license_link(collection):
    link = next((l for l in collection["links"] if l["rel"] == "license"), None)
    name = "Public domain or source terms" if collection["license"] == "other" else collection["license"]
    return f"[{name}]({link['href']})" if link else name


def facts(path, collection):
    """A definition table for one Collection."""
    rows = {
        "STAC Collection": f"[`{collection['id']}`]({REPO}/blob/main/{path.relative_to(ROOT)})",
        "Period": period(collection),
        "Bounding box (W, S, E, N)": bbox(collection),
        "Files": f"{len(collection.get('assets', {})):,}" + (f", {size(collection)}" if size(collection) else ""),
        "License": license_link(collection),
        "Providers": "; ".join(f"[{p['name']}]({p['url']})" if p.get("url") else p["name"]
                               for p in collection.get("providers", [])),
        "Keywords": ", ".join(collection.get("keywords", [])),
    }
    return "| | |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in rows.items() if v)


def main():
    datasets = ROOT / "datasets"
    datasets.mkdir(exist_ok=True)
    table, summaries = [], []
    for raw_path, raw in children(ROOT / "raw.json"):
        source = raw_path.parents[1].name
        title = raw["title"].replace(" (raw)", "")
        derived_catalog = ROOT / source / "derived/catalog.json"
        derived = children(derived_catalog) if derived_catalog.exists() else []

        page = [f"---\ntitle: \"{title}\"\n---\n",
                f"Directory: `{PATH}/{source}/` · [Source on GitHub]({REPO}/tree/main/{source})\n",
                "## Raw files\n", raw["description"] + "\n", facts(raw_path, raw)]
        for path, collection in derived:
            page += [f"## Derived: {collection['title']}\n", collection["description"] + "\n", facts(path, collection)]
        readme = (ROOT / source / "README.md").read_text().split("\n", 1)[1]  # drop the H1
        # Demote the README's headings one level so they nest under this one.
        page += ["## Layout and usage\n", readme.replace("\n### ", "\n#### ").replace("\n## ", "\n### ")]
        (datasets / f"{source}.md").write_text("\n".join(page))

        table.append(f"| [{title}](datasets/{source}.md) | `{source}/` | {period(raw)} | {size(raw)} | "
                     + ("<br>".join(c["title"] for _, c in derived) or "none") + " |")
        summaries.append(f"### [{title}](datasets/{source}.md)\n\n{raw['description']}\n")

    (ROOT / "index.md").write_text(f"""---
title: "ASCEND Data Catalog"
---

Shared datasets for NSF ASCEND Engine performers, stored at `{PATH}` on the MedicineBow cluster
(University of Wyoming ARCC) and described by a [STAC](https://stacspec.org) catalog.

- The data are on the cluster only. This site and the [GitHub repository]({REPO}) hold the STAC JSON, the
  build scripts and the documentation, not the data. Reading the files requires membership in the `cowy`
  project on MedicineBow.
- Each source has a `raw/` directory of unmodified vendor files and, for some, a `derived/` directory of
  analysis-ready products. [Repository layout](layout.md) describes the structure and how to add a source.
- The STAC root is `{PATH}/catalog.json`. All hrefs are relative, so any STAC client can walk it from there.

## Datasets

| Dataset | Directory | Period | Raw size | Derived products |
|---|---|---|---|---|
{chr(10).join(table)}

## Summaries

{chr(10).join(summaries)}
""")
    layout = (ROOT / "README.md").read_text().split("\n", 1)[1]
    (ROOT / "layout.md").write_text('---\ntitle: "Repository layout"\n---\n' + layout)
    print(f"wrote index.md, layout.md and {len(table)} pages in datasets/")


if __name__ == "__main__":
    main()
