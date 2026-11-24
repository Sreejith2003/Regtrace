"""Download the real privacy policies listed in scripts/policies.yaml.

Pages are saved to data/raw/policies/<id>.html with a manifest.json recording
the URL, retrieval time and SHA-256, so later changes to a policy are visible.

Usage (from the repo root, venv active):
    python scripts\\download_policies.py
    python scripts\\download_policies.py --only spotify bbc
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from regtrace.parsing import fetch_html

SOURCES = Path(__file__).with_name("policies.yaml")
DEFAULT_OUT = Path("data") / "raw" / "policies"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", nargs="+", metavar="ID", help="download only these ids")
    args = parser.parse_args()

    policies = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["policies"]
    if args.only:
        policies = [p for p in policies if p["id"] in args.only]
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}

    failed = []
    for i, policy in enumerate(policies):
        if i:
            time.sleep(1)
        try:
            html = fetch_html(policy["url"])
        except httpx.HTTPError as exc:
            print(f"  FAILED {policy['id']}: {exc}")
            failed.append(policy)
            continue
        path = args.out / f"{policy['id']}.html"
        path.write_text(html, encoding="utf-8")
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        changed = manifest.get(policy["id"], {}).get("sha256") not in (None, digest)
        manifest[policy["id"]] = {
            "company": policy["company"],
            "url": policy["url"],
            "retrieved": datetime.now(UTC).isoformat(timespec="seconds"),
            "sha256": digest,
        }
        print(f"  saved  {path} ({len(html) // 1024} KB){'  [changed]' if changed else ''}")

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Downloaded {len(policies) - len(failed)} of {len(policies)} into {args.out}")
    for policy in failed:
        print(f"Save {policy['url']} from your browser as {args.out / policy['id']}.html")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
