# goes-fdc-catalog

A Portolan catalog of NOAA's GOES-18 ABI Fire/Hot Spot Characterization as a virtual Zarr cube.

## Where things are documented

| File | Holds |
|---|---|
| `README.md` | The repository overview, the main design choices, the pipeline, and how to work here. A short file. |
| `docs/architecture.md` | Methods. It covers the source data, the build, the Zarr store, the catalog metadata, the measurements, and the Zarr findings. |
| `catalog/README.md` | The data, for humans: variables, codes, coverage, license, provenance. Published. |
| `catalog/AGENTS.md` | A short pointer for machine clients. Published. |
| `catalog/abi-l2-fdcc/README.md` and `AGENTS.md` | The read recipe, measured file layout, and the traps. Published. |
| `docs/conformance.md` | Validator findings and the accepted ones. |

Put a new fact in the one file that owns it, and link to it from the others.

## Ground rules

The [portolan-spec](https://github.com/portolan-sdi/portolan-spec) repo is ground truth for the Portolan specification. This catalog implements it. Zarr is outside the conformance surface ([#132](https://github.com/portolan-sdi/portolan-spec/issues/132)), so never describe the Zarr assets as conformant.

Before you document a command, flag, or API, verify it exists in the released tool. Run it first.

This repository was created from the [portolan-catalog-template](https://github.com/portolan-sdi/portolan-catalog-template) as a personal repo.

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

`local/` is gitignored. The Icechunk repo is a build product, not source.
Never commit it.
