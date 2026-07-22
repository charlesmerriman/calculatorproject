"""
rebuild_support_card_fixture.py

Rebuilds calculatorapi/fixtures/supportCards.json from a game-data source file
(id/name_en/rarity per card), matched by exact numeric id against what's
actually sitting in the DigitalOcean Space's support_cards/ folder.

Why id-based matching instead of name matching (see update_fixture_images.py):
most characters have 2-3 support cards across rarities/reprints that share the
exact same name (e.g. three different "Curren Chan" cards), which makes
name-only matching produce silent collisions. SupportCard.game_id is now a
unique DB column anchored on the same numeric id that prefixes each image's
filename in the Space, so matching on that id is unambiguous.

Referential integrity: supportsOnSupportBanner.json references SupportCard
rows by pk. Existing pks are never reassigned here - a source entry whose
game_id already has a row keeps that row's pk and only has its name/image
refreshed. New rows (ids not yet in the fixture) get new pks appended after
the current max. Entries with no matching image in the Space are left out of
the fixture entirely.

Run from backend/:
    python scripts/rebuild_support_card_fixture.py
"""

import json
import os
import re
from pathlib import Path

import boto3
from dotenv import load_dotenv

# ── Config ───────────────────────────────────────────────────────────────────

# Credentials and Spaces config come from backend/.env - the same variables
# settings.py uses. Never hardcode the keys here: this file is committed.
load_dotenv(Path(__file__).parent.parent / ".env")

BUCKET = os.environ["DO_SPACES_BUCKET_NAME"]
ENDPOINT = os.environ["DO_SPACES_ENDPOINT_URL"]
ACCESS_KEY = os.environ["DO_SPACES_ACCESS_KEY"]
SECRET_KEY = os.environ["DO_SPACES_SECRET_KEY"]

FIXTURES_DIR = Path(__file__).parent.parent / "calculatorapi" / "fixtures"
SOURCE_PATH = Path(__file__).parent / "data" / "support_cards_source.json"
FIXTURE_PATH = FIXTURES_DIR / "supportCards.json"

# Matches the numeric id prefix of a support card image key, e.g.
# "support_cards/30048-Mejiro-Ryan-gts.png" -> "30048". Anchored on the
# path segment + trailing '-' so an id can never prefix-match a longer one
# (id=300 must not match a key that starts with "30001-").
KEY_ID_RE = re.compile(r"^support_cards/(\d+)-")


def list_support_card_keys(client) -> dict[int, str]:
    """Returns {numeric id: full Spaces key} for every support_cards/ object."""
    paginator = client.get_paginator("list_objects_v2")
    id_to_key: dict[int, str] = {}
    for page in paginator.paginate(Bucket=BUCKET, Prefix="support_cards/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            m = KEY_ID_RE.match(key)
            if m:
                id_to_key[int(m.group(1))] = key
    return id_to_key


def main() -> None:
    print("Connecting to DigitalOcean Spaces …")
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="nyc3",
        config=boto3.session.Config(signature_version="s3v4"),
    )

    print("Listing support_cards/ objects …")
    image_by_id = list_support_card_keys(s3)
    print(f"  {len(image_by_id)} images found in the Space")

    source: list[dict] = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    print(f"  {len(source)} cards in source data")

    existing: list[dict] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    pk_by_game_id: dict[int, int] = {
        row["fields"]["game_id"]: row["pk"]
        for row in existing
        if row["fields"].get("game_id") is not None
    }
    rows_by_pk: dict[int, dict] = {row["pk"]: row for row in existing}
    next_pk = max(rows_by_pk, default=0) + 1

    preserved = 0
    updated_names = 0
    added = 0
    skipped: list[tuple[int, str]] = []

    for card in source:
        game_id: int = card["id"]
        name: str = card["name_en"]

        image_key = image_by_id.get(game_id)
        if image_key is None:
            skipped.append((game_id, name))
            continue

        if game_id in pk_by_game_id:
            pk = pk_by_game_id[game_id]
            row = rows_by_pk[pk]
            if row["fields"]["name"] != name:
                updated_names += 1
            row["fields"]["name"] = name
            row["fields"]["image"] = image_key
            preserved += 1
        else:
            rows_by_pk[next_pk] = {
                "model": "calculatorapi.supportcard",
                "pk": next_pk,
                "fields": {
                    "name": name,
                    "game_id": game_id,
                    "image": image_key,
                    "admin_comments": "",
                },
            }
            pk_by_game_id[game_id] = next_pk
            next_pk += 1
            added += 1

    rebuilt = [rows_by_pk[pk] for pk in sorted(rows_by_pk)]

    # ── Integrity checks before writing ─────────────────────────────────────
    pks = [row["pk"] for row in rebuilt]
    assert len(pks) == len(set(pks)), "duplicate pk detected"
    game_ids = [row["fields"]["game_id"] for row in rebuilt]
    assert len(game_ids) == len(set(game_ids)), "duplicate game_id detected"

    FIXTURE_PATH.write_text(
        json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("\nDone.")
    print(f"  {preserved} existing rows preserved (pk unchanged, {updated_names} had a stale name cleaned up)")
    print(f"  {added} new rows appended")
    print(f"  {len(rebuilt)} total rows in the rebuilt fixture")
    print(f"  {len(skipped)} source entries skipped (no matching image in the Space):")
    for game_id, name in skipped:
        print(f"    {game_id}  {name!r}")


if __name__ == "__main__":
    main()
