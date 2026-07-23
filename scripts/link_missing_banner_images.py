"""
link_missing_banner_images.py

Fills the `image` field for bannerTimelines.json rows that are currently empty,
by matching the banner name against images already in the DigitalOcean Space
under banner_timelines/.

This is the narrow-scope counterpart to update_fixture_images.py: that script
re-derives images for umas, support cards AND banners in one pass (re-running it
would re-fuzzy-match the carefully-set uma/support images and risk regressions).
This one only ever *fills empty* banner-timeline images and never touches the
other fixtures or overwrites an image that's already set — safe to run anytime a
batch of new timelines was added.

Reuses update_fixture_images.py's normalization, override table and fuzzy
matcher so results stay consistent with the original tooling.

Run from backend/ (dry-run):
    python scripts/link_missing_banner_images.py
Apply:
    python scripts/link_missing_banner_images.py --apply
"""

import json
import re
import sys
from pathlib import Path

import boto3

from update_fixture_images import (
    ACCESS_KEY,
    BANNER_OVERRIDES,
    ENDPOINT,
    SECRET_KEY,
    build_banner_index,
    list_keys,
    normalize,
    strip_rerun,
)

FIXTURES = Path(__file__).parent.parent / "calculatorapi" / "fixtures"
BT_PATH = FIXTURES / "bannerTimelines.json"

# Space filenames that are misspelled and so won't match the banner name exactly.
# normalized banner name -> exact Space key.
LOCAL_OVERRIDES = {
    "dantsu flame": "banner_timelines/Danstu Flame.png",  # 'Danstu' typo in the Space
}


def main() -> None:
    apply = "--apply" in sys.argv
    data = json.loads(BT_PATH.read_text(encoding="utf-8"))

    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="nyc3",
        config=boto3.session.Config(signature_version="s3v4"),
    )
    # normalized banner filename -> exact Space key
    banner_index = build_banner_index(list_keys(s3, "banner_timelines/"))

    def match(name: str) -> str | None:
        """Confident matches only: curated override, then exact (or rerun-
        stripped exact) name. No loose fuzzy — a wrong banner image is worse
        than a placeholder, and themed compound names fuzzy-match each other."""
        q = normalize(name)
        if q in BANNER_OVERRIDES:
            return BANNER_OVERRIDES[q]
        if q in LOCAL_OVERRIDES:
            return LOCAL_OVERRIDES[q]
        if q in banner_index:
            return banner_index[q]
        rq = normalize(strip_rerun(name))
        if rq != q and rq in banner_index:
            return banner_index[rq]
        return None

    filled, still_empty = [], []
    for entry in data:
        if entry["fields"].get("image"):
            continue  # never overwrite an existing link
        name = entry["fields"]["name"]
        if re.match(r"^\(All\)", name):
            continue  # composite banners have no single image, by design
        key = match(name)
        if key:
            entry["fields"]["image"] = key
            filled.append((entry["pk"], name, key))
        else:
            still_empty.append((entry["pk"], name))

    if apply and filled:
        BT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Filled {len(filled)} empty banner image(s):")
    for pk, name, key in filled:
        print(f"  pk={pk:3d}  {name[:45]:45s} -> {key}")
    print(f"\nStill empty ({len(still_empty)}) — no confident Space image (frontend shows a placeholder):")
    for pk, name in still_empty:
        print(f"  pk={pk:3d}  {name[:60]}")
    print("\nDRY RUN — re-run with --apply to write." if not apply else "\nAPPLIED to bannerTimelines.json.")


if __name__ == "__main__":
    main()
