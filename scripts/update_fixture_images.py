"""
update_fixture_images.py

Updates the `image` field in three Django fixture files by fuzzy-matching
fixture names against DigitalOcean Spaces object keys:

  umas.json          — Google Drive URLs → Spaces CDN URLs
  supportCards.json  — Google Drive URLs → Spaces CDN URLs
  bannerTimelines.json — null → Spaces CDN URLs (best-effort)

Run from backend/:
    python scripts/update_fixture_images.py

Prints a match report at the end. Any unmatched entries are left null and
listed so they can be reviewed and patched manually.
"""

import difflib
import json
import os
import re
from pathlib import Path

import boto3
from dotenv import load_dotenv

# ── Config ─────────────────────────────────────────────────────────────────────

# Credentials and Spaces config come from backend/.env — the same variables
# settings.py uses. Never hardcode the keys here: this file is committed.
load_dotenv(Path(__file__).parent.parent / ".env")

CDN_BASE = f"https://{os.environ['DO_SPACES_CDN_DOMAIN']}"
BUCKET = os.environ["DO_SPACES_BUCKET_NAME"]
ENDPOINT = os.environ["DO_SPACES_ENDPOINT_URL"]
ACCESS_KEY = os.environ["DO_SPACES_ACCESS_KEY"]
SECRET_KEY = os.environ["DO_SPACES_SECRET_KEY"]

FIXTURES_DIR = Path(__file__).parent.parent / "calculatorapi" / "fixtures"

# ── Hardcoded banner timeline overrides ────────────────────────────────────────
# Normalized fixture name → Spaces object key.
# Used for banners whose Spaces images use thematic names that won't fuzzy-match
# against the longer compound fixture name, or where the fuzzy score falls just
# below the cutoff.
BANNER_OVERRIDES: dict[str, str] = {
    # "Nice Nature (Cheerleader) + King Halo (Cheerleader)"
    "nice nature cheerleader king halo cheerleader": "banner_timelines/Cheerleader.jpg",
    # "Special Week (Summer) + Maruzensky (Summer)"
    "special week summer maruzensky summer": "banner_timelines/Summer.jpg",
    # "Tokai Teio (Anime) + Mejiro Mcqueen (Anime)"
    "tokai teio anime mejiro mcqueen anime": "banner_timelines/Anime 2025.jpg",
    # "Air Groove (Wedding) + Mayano Top Gun (Wedding)"  — first wedding banner (2025)
    "air groove wedding mayano top gun wedding": "banner_timelines/Wedding 2025.jpg",
    # "Grass Wonder (Fantasy) + El Condor Pasa (Fantasy)"
    "grass wonder fantasy el condor pasa fantasy": "banner_timelines/Fantasy.jpg",
    # "Symboli Rudolf (Festival) + Gold City (Festival)"
    "symboli rudolf festival gold city festival": "banner_timelines/(Festival).png",
    # "Winning Ticket (Steampunk) + Narita Taishin (Steampunk)"
    "winning ticket steampunk narita taishin steampunk": "banner_timelines/Steampunk.jpg",
    # "Sirius Symboli (The Twinkle Legends)" — fuzzy score just below cutoff
    "sirius symboli the twinkle legends": "banner_timelines/Sirius Symboli.png",
    # "Copano Rickey (Parade) + Smart Falcon (Parade)"
    "copano rickey parade smart falcon parade": "banner_timelines/Parade.png",
    # "Cesario (Wedding) + Mejiro Ramonu (Wedding)"  — second wedding banner (2026)
    "cesario wedding mejiro ramonu wedding": "banner_timelines/Wedding 2026.jpg",
    # "Cheval Grand (Summer) + Satono Crown (Summer)"
    "cheval grand summer satono crown summer": "banner_timelines/Summer 2026.jpg",
    # "K.S.Miracle (Alt Version) + Hishi Miracle (Alt Version)"
    "k s miracle alt version hishi miracle alt version": "banner_timelines/Alt 2025.png",
    # "Taiki Shuttle (Valentine) + Sounds of Earth (Valentine)"
    "taiki shuttle valentine sounds of earth valentine": "banner_timelines/Valentine.png",
}

# ── Normalization ──────────────────────────────────────────────────────────────

# Written-out stat names that can appear in support card fixture entries
STAT_ALIASES: dict[str, str] = {
    "stamina": "stm",
    "speed": "spd",
    "power": "pwr",
    "guts": "gts",
    "wisdom": "wts",
    "wit": "wts",
    "wits": "wts",
    "friend": "pls",
    "manager": "pls",
}


def normalize(s: str) -> str:
    """
    Produce a canonical form for fuzzy comparison:
      1. Lowercase
      2. Strip decoration chars: . ' ♡ ♥ ❤ ♪ & ( ) +
      3. Replace - and _ with space
      4. Collapse whitespace
      5. Substitute written-out stat names with their abbreviations
    """
    s = s.lower()
    s = re.sub(r"[.'♥♡❤♪&()+]", " ", s)
    s = re.sub(r"[-_]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for word, abbrev in STAT_ALIASES.items():
        s = re.sub(r"\b" + word + r"\b", abbrev, s)
    return s


def strip_rerun(name: str) -> str:
    """Remove a trailing '(Rerun)' qualifier so reruns resolve to the base image."""
    return re.sub(r"\s*\(Rerun\)\s*", "", name, flags=re.IGNORECASE).strip()


def extract_explicit_id(name: str) -> tuple[str | None, str]:
    """
    Some support card fixture names embed the Spaces game ID (e.g. 'Mejiro Ryan 30048').
    Returns (id_str, clean_name) when found, or (None, name) otherwise.
    """
    m = re.search(r"\b(3\d{4})\b", name)
    if m:
        return m.group(1), name[: m.start()].strip()
    return None, name


# ── Spaces helpers ─────────────────────────────────────────────────────────────

def list_keys(client, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k != prefix:
                keys.append(k)
    return keys


def cdn_url(key: str) -> str:
    # Store just the relative Spaces key, not the full CDN URL.
    # S3Boto3Storage.url() builds the full URL from the key at access time,
    # using the configured custom_domain. Storing the full URL causes
    # filepath_to_uri() to percent-encode '://', producing a broken double-URL.
    return key


# ── Index builders ─────────────────────────────────────────────────────────────

def build_uma_index(keys: list[str]) -> dict[str, str]:
    """
    Maps normalized name parts → Spaces key for every uma image.

    Spaces filename: '101501-TM-Opera-O.png'
    Name part:       'TM-Opera-O'  →  normalized: 'tm opera o'
    """
    index: dict[str, str] = {}
    for key in keys:
        filename = key.split("/")[-1]
        # Drop the numeric game-ID prefix (everything before the first '-')
        name_part = "-".join(filename.split("-")[1:]).rsplit(".", 1)[0]
        norm = normalize(name_part)
        index[norm] = key
    return index


def build_support_index(
    keys: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns two indexes built from support_cards/ keys:

    id_index:   game_id_str → Spaces key   (all IDs, used for explicit-ID lookups)
    name_index: normalized_name_with_stat → Spaces key  (30 000+ only; lowest ID wins
                when the same name appears under multiple game IDs)
    """
    id_index: dict[str, str] = {}
    # Collect 30 000+ entries by normalized name; we keep the lowest game ID per name.
    raw: dict[str, list[tuple[int, str]]] = {}

    for key in keys:
        filename = key.split("/")[-1]  # e.g. '30048-Mejiro-Ryan-gts.png'
        parts = filename.split("-")
        try:
            game_id = int(parts[0])
        except ValueError:
            continue

        id_index[parts[0]] = key

        if game_id < 30000:
            continue

        # Include the stat suffix so 'nakayama festa stm' ≠ 'nakayama festa wts'
        name_with_stat = "-".join(parts[1:]).rsplit(".", 1)[0]
        norm = normalize(name_with_stat)
        raw.setdefault(norm, []).append((game_id, key))

    name_index: dict[str, str] = {}
    for norm, candidates in raw.items():
        _, best_key = min(candidates, key=lambda x: x[0])
        name_index[norm] = best_key

    return id_index, name_index


def build_banner_index(keys: list[str]) -> dict[str, str]:
    """
    Maps normalized filename (no extension) → Spaces key for banner timeline images.
    """
    index: dict[str, str] = {}
    for key in keys:
        filename = key.split("/")[-1]
        name = filename.rsplit(".", 1)[0]
        norm = normalize(name)
        index[norm] = key
    return index


# ── Fuzzy matching helper ──────────────────────────────────────────────────────

def best_match(query: str, index: dict[str, str], cutoff: float) -> str | None:
    """Return the Spaces key for the closest fuzzy match, or None."""
    hits = difflib.get_close_matches(query, index.keys(), n=1, cutoff=cutoff)
    return index[hits[0]] if hits else None


# ── Per-fixture updaters ───────────────────────────────────────────────────────

def update_umas(uma_index: dict[str, str]) -> None:
    path = FIXTURES_DIR / "umas.json"
    data: list[dict] = json.loads(path.read_text())

    matched = 0
    unmatched: list[str] = []

    for entry in data:
        name: str = entry["fields"]["name"]

        # "(All)" entries have no corresponding Spaces image
        if re.match(r"^\(All\)", name):
            entry["fields"]["image"] = None
            continue

        # Reruns reuse the base character's image — strip the qualifier before matching
        query_name = strip_rerun(name) if re.search(r"\(Rerun\)", name, re.IGNORECASE) else name
        query = normalize(query_name)

        key = best_match(query, uma_index, cutoff=0.65)
        if key:
            entry["fields"]["image"] = cdn_url(key)
            matched += 1
        else:
            entry["fields"]["image"] = None
            unmatched.append(f"  pk={entry['pk']:3d}  {name!r}  (query: {query!r})")

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nUmas: {matched} matched, {len(unmatched)} unmatched")
    for line in unmatched:
        print(line)


def update_support_cards(
    id_index: dict[str, str],
    name_index: dict[str, str],
) -> None:
    path = FIXTURES_DIR / "supportCards.json"
    data: list[dict] = json.loads(path.read_text())

    matched = 0
    unmatched: list[str] = []

    # PK-level overrides for names that can't be matched automatically
    pk_overrides: dict[int, str] = {
        9:  "support_cards/30021-Tazuna-Hayakawa-pls.png",  # "Tazuna" (short name, full key is Tazuna Hayakawa)
        42: "support_cards/30080-Sasami-Anshinzawa-pls.png",  # "S. Anshinzawa"
    }

    for entry in data:
        pk: int = entry["pk"]
        name: str = entry["fields"]["name"]

        # ── Hard override ──────────────────────────────────────────────────────
        if pk in pk_overrides:
            entry["fields"]["image"] = cdn_url(pk_overrides[pk])
            matched += 1
            continue

        # ── Strip rerun before any further matching ────────────────────────────
        if re.search(r"\(Rerun\)", name, re.IGNORECASE):
            name = strip_rerun(name)

        # ── Explicit game ID embedded in the fixture name ──────────────────────
        explicit_id, clean_name = extract_explicit_id(name)
        if explicit_id and explicit_id in id_index:
            entry["fields"]["image"] = cdn_url(id_index[explicit_id])
            matched += 1
            continue

        # ── Fuzzy match against 30 000+ name index ─────────────────────────────
        query = normalize(clean_name)
        key = best_match(query, name_index, cutoff=0.60)
        if key:
            entry["fields"]["image"] = cdn_url(key)
            matched += 1
        else:
            entry["fields"]["image"] = None
            unmatched.append(
                f"  pk={entry['pk']:3d}  {entry['fields']['name']!r}  (query: {query!r})"
            )

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nSupport cards: {matched} matched, {len(unmatched)} unmatched")
    for line in unmatched:
        print(line)


def update_banner_timelines(banner_index: dict[str, str]) -> None:
    path = FIXTURES_DIR / "bannerTimelines.json"
    data: list[dict] = json.loads(path.read_text())

    matched = 0
    unmatched: list[str] = []

    for entry in data:
        name: str = entry["fields"]["name"]

        # "(All)" entries have no image
        if re.match(r"^\(All\)", name):
            entry["fields"]["image"] = None
            continue

        query = normalize(name)

        # ── Hardcoded overrides for known theme-named images ───────────────────
        if query in BANNER_OVERRIDES:
            entry["fields"]["image"] = cdn_url(BANNER_OVERRIDES[query])
            matched += 1
            continue

        # ── Fuzzy match ────────────────────────────────────────────────────────
        key = best_match(query, banner_index, cutoff=0.60)
        if key:
            entry["fields"]["image"] = cdn_url(key)
            matched += 1
        else:
            entry["fields"]["image"] = None
            unmatched.append(f"  pk={entry['pk']:3d}  {name!r}  (query: {query!r})")

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nBanner timelines: {matched} matched, {len(unmatched)} unmatched")
    for line in unmatched:
        print(line)


# ── Main ───────────────────────────────────────────────────────────────────────

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

    print("Listing objects …")
    uma_keys = list_keys(s3, "umas/")
    support_keys = list_keys(s3, "support_cards/")
    banner_keys = list_keys(s3, "banner_timelines/")
    print(f"  {len(uma_keys)} uma images")
    print(f"  {len(support_keys)} support card images")
    print(f"  {len(banner_keys)} banner timeline images")

    uma_index = build_uma_index(uma_keys)
    id_index, name_index = build_support_index(support_keys)
    banner_index = build_banner_index(banner_keys)

    update_umas(uma_index)
    update_support_cards(id_index, name_index)
    update_banner_timelines(banner_index)

    print("\nDone. Review any unmatched entries above.")
    print("To load the updated fixtures:")
    print("  python manage.py loaddata calculatorapi/fixtures/umas.json")
    print("  python manage.py loaddata calculatorapi/fixtures/supportCards.json")
    print("  python manage.py loaddata calculatorapi/fixtures/bannerTimelines.json")


if __name__ == "__main__":
    main()
