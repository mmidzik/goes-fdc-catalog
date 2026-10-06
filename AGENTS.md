# goes-fdc-catalog

A Portolan catalog of NOAA's GOES ABI Fire/Hot Spot Characterization as a virtual Zarr cube. The design is in `docs/architecture.md`. Read it before you change the pipeline or the catalog layout.

## Ground rules

The [portolan-spec](https://github.com/portolan-sdi/portolan-spec) repo is ground truth for the Portolan specification. This catalog implements it. Zarr is outside the conformance surface ([#132](https://github.com/portolan-sdi/portolan-spec/issues/132)), so never describe the Zarr assets as conformant.

Before you document a command, flag, or API, verify it exists in the released tool. Run it first.

This repository is personal (`mmidzik`) and is not moving to `portolan-sdi` for now. It was created from `portolan-catalog-template`, and the org governance workflows were removed.

## Python environment

Use `uv`. Never `pip install` into the system Python.

```bash
uv sync                 # create .venv from uv.lock
uv add <package>        # add a dependency and update uv.lock
uv run pytest           # unit tests
uv run goes-fdc build --help
```

Commit `uv.lock`. Never commit `.venv/` or anything under `local/`.

## Commits and pull requests

Write commits in conventional form. Commit message bodies, issue bodies, pull request bodies, and lasting code comments follow `.claude/output-styles/simplified-technical-english.md`. `.claude/hooks/writing_check.py` checks `gh issue create` and `gh pr create`.

Never bypass the CI gates. Green means green.

## This repository



### The publish boundary

`catalog/` is the published catalog. Everything in it is published, and
nothing outside it ever is. Do not move a file into `catalog/` to make it
publish, and do not add a path outside `publish_dir` to `tools/publish.py`.
The boundary is the only thing standing between a scratch file and a public
bucket, and it holds because it is structural rather than a list of
exclusions.

### Data never enters git

Never commit a GeoParquet, COG, PMTiles, Zarr, or COPC file. If a gate needs
bytes to check, generate them in CI. Git keeps every version of a binary
forever and deleting it later reclaims nothing.

### The conformance allow-list

`ACCEPTED` in `tests/test_conformance.py` ships empty. Never add an entry
without a matching row in `docs/conformance.md` giving the rule, where it
fires, why it is accepted, and the issue tracking its removal.

### Published agent guides

Every claim in a `catalog/**/AGENTS.md` is either quoted from a source or
measured from the data. An invented join key or column name produces a
confident wrong answer that nothing downstream catches.

### The links back to this repository

`catalog/catalog.json` carries a `vcs` link and an `issues` link, both absolute
URLs to `github.com/mmidzik/goes-fdc-catalog`. The repository sits outside the
published catalog, so a relative href would resolve against the public base URL.
Update both if the repository moves.

### Pipeline output stays local

`local/` and `pipeline/scratch/` are gitignored. The Icechunk repo and the
Kerchunk parquet are build products, not source. Never commit them.
