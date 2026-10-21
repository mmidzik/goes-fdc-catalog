# Portolan alignment plan: goes-fdc-catalog

## 1. Purpose

This plan brings the `goes-fdc-catalog` repository in line with Portolan specification v0.2.0 and the git-backed catalog best practice (`specs/best-practices/git-backed-catalogs.md` at tag `v0.2.0` of `portolan-sdi/portolan-spec`). It also prepares the repository for its first upload to Source Cooperative.

The reference implementation for comparison is `portolan-mirrors/firms-catalog`. Where that repository departs from the best practice (it commits an absolute `self` link in the tracked tree), this plan follows the best practice.

## 2. Scope

In scope:

- The Portolan schema version declared by every catalog and collection.
- The rashid version range used by the conformance gate.
- The publish configuration, the publish tool, and the data staging location.
- The scope, identifier, and title of the root catalog.
- The continuous integration workflow.
- Stale references in documentation and tooling.

Out of scope:

- The first upload to Source Cooperative.
- The scheduled update workflow.
- Expansion of the cube beyond the existing 24-scan smoke test.
- Adoption of rashid 0.2.x or 0.3.x.

## 3. Assumptions and decisions

| ID | Item | Value | Status |
|---|---|---|---|
| A1 | Portolan schema | `https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json` | Set |
| A2 | rashid range | `>=0.1.8,<0.2.0`. 0.1.8 is the first release that carries the v0.2.0 rules. | Set |
| A3 | Source Cooperative account | Personal account of Maya Midzik. Account name is `<ACCOUNT>`. | Placeholder, pending Maya Midzik |
| A4 | `write_prefix` | `s3://us-west-2.opendata.source.coop/<ACCOUNT>/goes-fdc-catalog` | Placeholder, depends on A3 |
| A5 | `public_base` | `https://data.source.coop/<ACCOUNT>/goes-fdc-catalog` | Placeholder, depends on A3 |
| A6 | Root catalog scope | GOES ABI Fire/Hot Spot Characterization only. The repository name and bucket prefix `goes-fdc-catalog` do not change. | Set |
| A7 | Root catalog `id` | `goes-fdc` | Set |
| A8 | Root catalog `title` | `GOES ABI Fire/Hot Spot Characterization (NOAA GOES-R)` | Set |
| A9 | Satellite sub-catalogs | `catalog/goes-18/` stays as the first sub-catalog. Later satellites get sibling sub-catalogs. | Set |
| A10 | Data staging directory | `local/publish`, inside the gitignored `local/` directory | Set |
| A11 | Workflow security | All third-party actions are pinned by commit SHA. zizmor runs in CI. | Set |
| A12 | Root `self` link | `tools/publish.py` adds it to the uploaded bytes. The tracked `catalog/catalog.json` has no `self` link. | Set |

## 4. Phase 1: Specification version

### 4.1 Work

1. Replace `portolan/v0.1.1` with `portolan/v0.2.0` in `stac_extensions` in these files:
   - `catalog/catalog.json`
   - `catalog/goes-18/catalog.json`
   - `catalog/goes-18/abi-l2-fdcc/collection.json`
2. Update the schema URI that `pipeline/src/goes_fdc/collection.py` writes, so a regenerated collection keeps v0.2.0.
3. Set the rashid range to `>=0.1.8,<0.2.0` in all four places that name it:
   - `MIN_VERSION` and `SPEC` in `tests/test_conformance.py`
   - The install step in `.github/workflows/ci.yml` (until Phase 4 replaces it)
   - The `dev` dependency group in `pyproject.toml`, then `uv lock`
   - The "rashid version floor" section of `docs/conformance.md`
4. Rewrite the floor rationale in `docs/conformance.md`. State that 0.1.8 is the first release with the v0.2.0 rules. Remove the claim that the same range is in `portolan-cli/pyproject.toml`.

### 4.2 Outputs

- `catalog/catalog.json`, `catalog/goes-18/catalog.json`, and `collection.json`, each declaring v0.2.0.
- One rashid range, stated identically in four places.

### 4.3 Acceptance criteria

- `grep -rn "v0.1.1" catalog pipeline tests` returns no matches.
- `uv run python tests/run_all.py` passes.
- `uv run rashid check catalog --schema` reports 0 errors.

## 5. Phase 2: Publish configuration and tooling

### 5.1 Work

1. In `catalog.publish.yaml`:
   - Set `write_prefix` and `public_base` to the values in A4 and A5.
   - Replace the PROVISIONAL header comment with a statement that the target is the personal Source Cooperative account.
   - Set `data_dir: local/publish`.
   - Keep `profile` commented out. Add a note that gives the profile under which the personal credentials are stored, once A3 is set.
2. In `.gitignore`, remove the `staging/*/data/` and `pipeline/scratch/` entries. Keep `local/`.
3. Move any staged files from `staging/goes/data/` to `local/publish/`. Delete the empty `staging/` and `pipeline/scratch/` directories.
4. Regenerate `catalog/goes-18/abi-l2-fdcc/collection.json` with `goes_fdc.collection --public-base` set to the A5 value, so the `icechunk` and `kerchunk` asset hrefs use the new base.
5. Update the usage string at `pipeline/src/goes_fdc/collection.py:4` and the commands in `README.md` to the A5 base and to `local/publish`.
6. Port the following from `firms-catalog/tools/publish.py` into `tools/publish.py`:
   - Credential precedence: when `AWS_ACCESS_KEY_ID` is set, ignore `profile`.
   - Optional `endpoint_url` support through an `s3_client` helper.
   - The botocore retry configuration, including HTTP 520, 522, and 524 and dropped connections.
   - The multipart transfer configuration (64 MB threshold and chunk size).
7. Add root `self` link injection to `tools/publish.py`:
   - When the tool uploads `catalog.json` at the root of `publish_dir`, it inserts `{"rel": "self", "href": "<public_base>/catalog.json", "type": "application/json"}` as the first link in the uploaded bytes.
   - The tool does not modify the tracked file.
   - The dry run prints the link it would add.
8. Add tests to `tests/test_publish.py`:
   - The uploaded root catalog contains exactly one `self` link with the expected href.
   - No other uploaded file gains a `self` link.
   - The tracked `catalog/catalog.json` is unchanged after a dry run.
9. Remove the "then see SETUP.md" text from `tools/publish.py:314` and `tools/upload_data.py:159`. Point to the "Working on this repository" section of `README.md` instead.

### 5.2 Outputs

- A publish configuration that specifies the personal account, with placeholders where A3 is open.
- One staging location, `local/publish`.
- A publish tool that writes the root `self` link and retries transient Source Cooperative failures.

### 5.3 Acceptance criteria

- `uv run python tools/publish.py` (dry run) lists only files under `catalog/` and prints the `self` link.
- `uv run python tools/upload_data.py` (dry run) lists the Icechunk and Kerchunk files from `local/publish`.
- `uv run python tests/run_all.py` passes, including the new publish tests.
- `git status` shows no files under `local/`.

## 6. Phase 3: Root catalog scope

### 6.1 Work

1. In `catalog/catalog.json`:
   - Set `id` to A7 and `title` to A8.
   - Rewrite `description` to cover the Fire/Hot Spot Characterization product only. Keep the statements that NOAA produces the data and that the catalog holds references, not pixel data.
   - Add `"title": "GOES ABI Fire/Hot Spot Characterization (NOAA GOES-R)"` to the `root` link.
   - Add a `providers` array: NOAA NESDIS with roles `producer` and `licensor`, and Maya Midzik with roles `host` and `processor` and `url` `https://github.com/mmidzik/goes-fdc-catalog`.
2. Update the root title in the `root` and `parent` links of `catalog/goes-18/catalog.json` and the `root` link of `collection.json`. Make the generator in `goes_fdc/collection.py` write the same title.
3. In `collection.json`, change the `url` of the mmidzik provider from `.../issues` to `https://github.com/mmidzik/goes-fdc-catalog`. Make the same change in the generator.
4. Update the headings and scope statements in `catalog/README.md` and `catalog/AGENTS.md` to match A6 and A8. Every claim in `AGENTS.md` stays quoted from a source or measured from the data.
5. Update the `goes-18` sub-catalog description to name FDC products, not all GOES-18 products.

### 6.2 Outputs

- A root catalog scoped to FDC, with an identifier and title that match the repository name.
- Consistent titles across all `root` and `parent` links.

### 6.3 Acceptance criteria

- `grep -rn "goes-abi\|GOES ABI (NOAA GOES-R)" catalog pipeline` returns no matches.
- The stac-check note "Links in catalogs and collections should always have a 'title' field" no longer appears for `catalog.json`.
- `uv run python tests/run_all.py` passes.

## 7. Phase 4: Continuous integration

### 7.1 Work

1. Replace the pip-based steps in `.github/workflows/ci.yml` with uv:
   - Install uv with `astral-sh/setup-uv`.
   - Run `uv sync --frozen --group dev`.
   - Run `uv run pyflakes tools/*.py tests/*.py pipeline/src pipeline/tests`.
   - Run `uv run pytest`.
   - Run `uv run python tests/run_all.py` with `CI_LIGHT=1`.
2. Remove the separate rashid and stac-check install. `uv.lock` becomes the source for validator versions. Keep stac-check unpinned in `pyproject.toml`, so the stac-check exemption still expires when upstream fixes the crash. Record in `docs/conformance.md` that `uv lock --upgrade-package stac-check` is the step that picks up a new release.
3. Pin every third-party action in `ci.yml` by full commit SHA, with the tag in a trailing comment. This applies to `actions/checkout`, `actions/setup-python` (if still used), and `astral-sh/setup-uv`.
4. Set `persist-credentials: false` on every `actions/checkout` step. This clears the zizmor `artipacked` finding.
5. Add a zizmor step to `ci.yml`: `uvx zizmor --offline .github/workflows`. Pin the zizmor version.
6. Leave `.github/workflows/vale.yml` on `portolan-sdi/portolan-ops/...@v1`. `zizmor.yml` already allows a ref pin for that path.

### 7.2 Outputs

- A CI workflow that installs from `uv.lock`. It runs the pipeline unit tests and lint, the catalog gates, and the workflow audit.

### 7.3 Acceptance criteria

- `uvx zizmor --offline .github/workflows` reports 0 findings that are not suppressed.
- CI passes on a pull request.
- The CI log shows `pytest` collecting the tests in `pipeline/tests`.

## 8. Phase 5: Documentation cleanup

### 8.1 Work

1. In `README.md`:
   - Remove the TODO "Write the goes-18/abi-l2-fdcc collection, validate it, and record accepted findings". The collection exists and validates.
   - Remove the sentence that says the collection README and AGENTS.md "arrive with the first collection".
   - Replace "The path in `catalog.publish.yaml` is a guess based on the FIRMS mirror" with the A3 status.
   - Replace `staging/goes/data/` with `local/publish/`.
2. In `docs/conformance.md`, replace the statement that the Zarr asset findings are recorded there. State that rashid reports no error-severity findings for the Zarr assets, and list the warnings by rule ID.
3. In `docs/architecture.md`, remove the instructions to work through the template's `SETUP.md`.

### 8.2 Outputs

- Documentation that matches the repository state after Phases 1 to 4.

### 8.3 Acceptance criteria

- `grep -rn "SETUP.md\|staging/goes" --include=*.md --include=*.py .` (excluding `.venv/`) returns no matches.
- The Vale workflow passes with no new errors.

## 9. Sequence

The phases run in order 1 to 5. Phases 1 and 3 both edit the catalog JSON files, and Phase 2 regenerates `collection.json`. They run in sequence on one branch. Phase 4 is independent of the catalog files and can run on its own branch. Each phase is one commit in conventional form.

## 10. Open items

| Item | Owner | Blocks |
|---|---|---|
| Source Cooperative account name (A3) | Maya Midzik | Final values of A4 and A5. Phase 2 runs with the placeholder and is completed when A3 is set. |
| Catalog `license` value | Maya Midzik | No phase of this plan. It is listed in the README TODO. |
