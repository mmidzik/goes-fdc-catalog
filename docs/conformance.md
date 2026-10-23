# Portolan Conformance

Conformance means passing [rashid](https://github.com/portolan-sdi/rashid),
not claiming to conform, so it runs in CI:

```bash
python3 tests/test_conformance.py
```

That gate fails on any error-severity finding whose rule is not listed below.
The list starts empty and it must never grow without a row here. A known
deviation with an issue number is a debt someone can pay off. A silently
widened allow-list is a false claim about what this catalog conforms to.

## The rashid version floor

The gate needs rashid `>=0.1.8,<0.2.0`. It reads `rashid --version` and fails
outside that range. It also fails when rashid is absent, and prints the install
command. A skip would report a green run for a catalog that no validator read.

The catalog declares Portolan v0.2.0. The floor is 0.1.8 because that is the
first rashid release that carries the v0.2.0 rules. An older rashid reports an
error for a `self` link and for an absolute structural `href`, which v0.2.0
allows.

Three places name this range: `tests/test_conformance.py`, the `dev` group in
`pyproject.toml`, and this page. Change all three together. CI installs from
`uv.lock`, so the lock file must resolve inside the range.

The upper bound stops an unreviewed 0.2 rule set from changing what this gate
means. Raise both bounds together when you move to 0.2, and read the new rules
first.

This file also records workarounds for the other validator CI runs. Those are
not conformance debts, because the catalog is correct and the validator is not.
They live here so nobody has to read CI code to find out why a gate skips
something.

## Accepted deviations

None. `tests/test_conformance.py` runs with `--no-data`, so it does not read the
Zarr assets. As of 2026-10-21, `rashid check catalog --schema` (rashid 0.1.8)
reports 0 errors. Warnings and info findings are not gate failures. It reports
these:

| Rule | Severity | Where | Reason |
|---|---|---|---|
| PTL-AST-003 | warning | `icechunk` asset | No `file:checksum` or `file:size`. The asset is a directory and has no single checksum. |
| PTL-PRO-002 | info | `abi-l2-fdcc` | No `canonical` link. NOAA publishes no STAC catalog for FDC. |


## Validator workarounds

### stac-check reports a dialect crash on every collection

`tests/test_stac_valid.py` exempts one stac-check failure:

```
'list' object has no attribute 'get'
[Schema: https://schemas.portolan-sdi.org/portolan/vX.Y.Z/schema.json]. Error in Extensions.
```

The Portolan schema is valid draft-07, and rashid validates catalogs against it
cleanly. `stac-validator`, which stac-check uses, hardcodes the JSON Schema
2020-12 dialect and ignores the `$schema` a schema declares. The profile schema
uses the draft-07 tuple form of `items` in `valid_bbox`, which means something
different under 2020-12, so the library raises instead of validating.

Tracked upstream at <https://github.com/stac-utils/stac-check/issues/159>,
and on the Portolan side at
<https://github.com/portolan-sdi/portolan-spec/issues/157>.

The exemption matches that exact message, and only when the failing schema is a
Portolan profile schema. Every other stac-check error still fails the build,
and the gate prints how many objects took the exemption.

The exemption expires on its own. The gate fails once stac-check stops emitting
the crash on a collection or item that declares the profile schema, and tells
you to delete both the exemption and this section. CI installs stac-check from
`uv.lock`, so a new release reaches CI only when the lock file moves. Run
`uv lock --upgrade-package stac-check` to take it. `pyproject.toml` sets no
range for stac-check, so that command always takes the newest release.

`tests/test_stac_valid.py` also fails when stac-check is absent, and prints the
install command. `pyproject.toml` sets no version range for stac-check. The
rashid floor exists because that gate asserts named rules. This gate asserts no
stac-check rule. It needs the opposite property. A range holds the exemption
open after the upstream fix ships.
