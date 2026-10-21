#!/usr/bin/env python3
"""The publish contract: only the published directory is ever uploaded.

This is the gate that turns the three-file-category model into an enforced
property. It builds a temp tree holding all three categories, asks the
publisher what it would upload, and asserts set equality — so a leak fails and
a missing file fails too.

No network, no AWS, no credentials.

Run: python3 tests/test_publish.py
"""
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from publish import (  # noqa: E402
    Upload,
    aws_session,
    collect_uploads,
    content_type_for,
    is_unchanged,
    split_s3_uri,
    unedited_sentinels,
    unset_placeholders,
    upload_all,
    with_self_link,
)

errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --- what gets uploaded, and what never does ---------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    # Category 1: tracked and published.
    write(root / "catalog/catalog.json", "{}")
    write(root / "catalog/README.md")
    write(root / "catalog/AGENTS.md")
    write(root / "catalog/roads/collection.json")
    write(root / "catalog/roads/thumbnail.png")
    write(root / "catalog/roads/styles/default.json")
    write(root / "catalog/_assets/logo.svg")

    # Category 2: tracked, never published.
    write(root / "tools/publish.py")
    write(root / "tests/test_publish.py")
    write(root / "docs/conformance.md")
    write(root / "README.md")
    write(root / "AGENTS.md")
    write(root / "CLAUDE.md")
    write(root / "catalog.publish.yaml")
    write(root / ".github/workflows/ci.yml")

    # Dotfiles inside the published directory are tracked but not uploaded.
    write(root / "catalog/_assets/.gitkeep", "")
    write(root / "catalog/.portolan/state.json")

    config = {
        "write_prefix": "s3://a-bucket/a/prefix",
        "public_base": "https://data.example.org/a/prefix",
        "publish_dir": "catalog",
    }
    keys = {u.key for u in collect_uploads(config, root)}

    expected = {
        "a/prefix/catalog.json",
        "a/prefix/README.md",
        "a/prefix/AGENTS.md",
        "a/prefix/roads/collection.json",
        "a/prefix/roads/thumbnail.png",
        "a/prefix/roads/styles/default.json",
        "a/prefix/_assets/logo.svg",
    }
    check(keys == expected, f"upload set wrong.\n  extra:   {keys - expected}"
                            f"\n  missing: {expected - keys}")

    # The bare-prefix case: no prefix at all.
    flat = dict(config, write_prefix="s3://a-bucket")
    check(
        {u.key for u in collect_uploads(flat, root)}
        == {k.removeprefix("a/prefix/") for k in expected},
        "keys are wrong when write_prefix names no prefix",
    )

# --- the root self link -----------------------------------------------
# The publish step adds an absolute self link to the root catalog only. The
# tracked file keeps none, and no other object gains one.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    tracked = '{\n  "id": "x",\n  "links": [\n    {"rel": "root", "href": "./catalog.json"}\n  ]\n}\n'
    write(root / "catalog/catalog.json", tracked)
    write(root / "catalog/sub/catalog.json", tracked)
    config = {
        "write_prefix": "s3://a-bucket/a/prefix",
        "public_base": "https://data.example.org/a/prefix/",
        "publish_dir": "catalog",
    }
    by_key = {u.key: u for u in collect_uploads(config, root)}

    top = by_key["a/prefix/catalog.json"]
    check(top.body is not None, "the root catalog carries rewritten bytes")
    links = json.loads(top.body)["links"] if top.body else []
    selfs = [link for link in links if link["rel"] == "self"]
    check(
        selfs == [{
            "rel": "self",
            "href": "https://data.example.org/a/prefix/catalog.json",
            "type": "application/json",
        }],
        f"exactly one absolute self link, got {selfs}",
    )
    check(links[:1] == selfs, "the self link is first")
    check(top.size() == len(top.body or b""), "size counts the uploaded bytes")

    check(by_key["a/prefix/sub/catalog.json"].body is None,
          "a sub-catalog gains no self link")
    check((root / "catalog/catalog.json").read_text() == tracked,
          "the tracked root catalog is unchanged")

    again = with_self_link(top.body or b"{}", config["public_base"])
    check(
        [link["rel"] for link in json.loads(again)["links"]].count("self") == 1,
        "an existing self link is replaced, not duplicated",
    )

# --- the placeholder guard ---------------------------------------------
check(
    unset_placeholders({
        "write_prefix": "s3://b/<ACCOUNT>/x",
        "public_base": "https://data.example.org/<ACCOUNT>/x",
    }) == ["<ACCOUNT>"],
    "an unset account is reported",
)
check(
    unset_placeholders({
        "write_prefix": "s3://b/acct/x",
        "public_base": "https://data.example.org/acct/x",
    }) == [],
    "a set account is accepted",
)

# --- split_s3_uri ------------------------------------------------------
check(split_s3_uri("s3://b/a/c") == ("b", "a/c"), "plain uri")
check(split_s3_uri("s3://b/a/c/") == ("b", "a/c"), "trailing slash")
check(split_s3_uri("s3://b") == ("b", ""), "bare bucket")
check(split_s3_uri("s3://b/") == ("b", ""), "bare bucket, trailing slash")

# --- content types -----------------------------------------------------
check(content_type_for(Path("a/catalog.json")) == "application/json",
      "plain json")
check(
    content_type_for(Path("a/styles/default.json"))
    == "application/vnd.mapbox.style+json",
    "json under styles/ is a MapLibre style",
)
check(
    content_type_for(Path("a/roads.style.json"))
    == "application/vnd.mapbox.style+json",
    "*.style.json is a MapLibre style",
)
check(
    content_type_for(Path("a/d.parquet")) == "application/vnd.apache.parquet",
    "parquet",
)
check(content_type_for(Path("a/x.unknown")) == "application/octet-stream",
      "unknown suffix falls back")

# --- change detection --------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    local = write(Path(tmp) / "f.json", "hello")
    digest = hashlib.md5(b"hello").hexdigest()  # noqa: S324
    upload = Upload(local, "k", "application/json")

    check(is_unchanged(upload, {"k": (5, digest)}), "identical bytes")
    check(is_unchanged(upload, {"k": (5, f'"{digest}"')}), "quoted etag")
    check(not is_unchanged(upload, {}), "absent key")
    check(not is_unchanged(upload, {"other": (5, digest)}), "key mismatch")
    check(not is_unchanged(upload, {"k": (5, "0" * 32)}), "etag differs")
    check(not is_unchanged(upload, {"k": (9, digest)}), "size differs")
    check(is_unchanged(upload, {"k": (5, "abc-2")}), "multipart: size only")

# --- the sentinel guard ------------------------------------------------
check(
    unedited_sentinels({
        "write_prefix": "s3://EXAMPLE-BUCKET/EXAMPLE-PREFIX",
        "public_base": "https://example.invalid/EXAMPLE-PREFIX",
    }) != [],
    "an unedited config is refused",
)
check(
    unedited_sentinels({
        "write_prefix": "s3://real/prefix",
        "public_base": "https://data.example.org/prefix",
    }) == [],
    "an edited config is accepted",
)

# --- the parallel upload pool ------------------------------------------
# A fake session stands in for boto3, so this stays offline and has no
# credentials. It records every call and fails one chosen key.
class FakeClient:
    def __init__(self, calls: list, fail_key: str | None) -> None:
        self.calls = calls
        self.fail_key = fail_key

    def upload_file(self, local, bucket, key, ExtraArgs, **kwargs):
        if key == self.fail_key:
            raise RuntimeError("boom")
        self.calls.append((local, bucket, key, ExtraArgs["ContentType"]))

    def put_object(self, Bucket, Key, Body, ContentType):
        if Key == self.fail_key:
            raise RuntimeError("boom")
        self.calls.append((Body, Bucket, Key, ContentType))


class FakeSession:
    def __init__(self, fail_key: str | None = None) -> None:
        self.calls: list = []
        self.clients = 0
        self.fail_key = fail_key

    def client(self, name, **kwargs):
        self.clients += 1
        return FakeClient(self.calls, self.fail_key)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    batch = [
        Upload(write(root / f"f{i}.json"), f"p/f{i}.json", "application/json")
        for i in range(50)
    ]

    session = FakeSession()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        failed = upload_all(session, "a-bucket", batch)
    check(failed == [], "no failures")
    check(
        {c[2] for c in session.calls} == {u.key for u in batch},
        "every object is uploaded exactly once",
    )
    # Progress is batched, not one line per object.
    check(
        len(out.getvalue().splitlines()) < len(batch),
        "progress does not print one line per object",
    )
    check(
        {c[3] for c in session.calls} == {"application/json"},
        "the content type reaches upload_file",
    )
    check(
        {c[1] for c in session.calls} == {"a-bucket"},
        "the bucket reaches upload_file",
    )

    # One bad object names itself and does not stop the other uploads.
    session = FakeSession(fail_key="p/f7.json")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        failed = upload_all(session, "a-bucket", batch)
    check(failed == ["p/f7.json"], f"the failed key is named, got {failed}")
    check(len(session.calls) == len(batch) - 1, "one failure stops nothing")
    check("p/f7.json" in err.getvalue(), "the failed key goes to stderr")

# --- the AWS session ---------------------------------------------------
# boto3 is not a dependency of this template, so this part is skipped when
# boto3 is absent. CI runs without it. A fixture AWS config keeps the check
# off the developer's own profiles.
if importlib.util.find_spec("boto3") is None:
    print("note: boto3 is not installed; skipping the aws_session checks")
else:
    with tempfile.TemporaryDirectory() as tmp:
        conf = write(
            Path(tmp) / "aws-config",
            "[default]\nregion = us-east-1\n\n"
            "[profile a-profile]\nregion = eu-west-1\n",
        )
        os.environ["AWS_CONFIG_FILE"] = str(conf)
        os.environ.pop("AWS_PROFILE", None)

        named = aws_session({"profile": "a-profile", "region": "us-west-2"})
        check(named.profile_name == "a-profile", "profile reaches the session")
        check(named.region_name == "us-west-2", "region reaches the session")

        inherited = aws_session({"profile": "a-profile"})
        check(
            inherited.region_name == "eu-west-1",
            "no region means the region of the profile",
        )

        bare = aws_session({})
        check(bare.profile_name == "default", "no profile means the default")

        empty = aws_session({"profile": "", "region": ""})
        check(empty.profile_name == "default", "an empty profile is no profile")

if errors:
    print("\n".join(f"error  {e}" for e in errors))
    raise SystemExit(1)
print("OK: publish contract holds")
