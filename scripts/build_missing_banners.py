"""
build_missing_banners.py

Backfills the BannerUma / BannerSupport rows (and their through-table links)
for banner timelines that were added to bannerTimelines.json without their
featured characters — timelines pk 149-196, whose Uma/Support tables stop at
pk 148.

Source of truth is the master timeline sheet (scripts/data/timeline_master.csv),
the same sheet the timeline rows themselves came from. Each banner row's
"Banner Uma" / "Banner Support" columns list the featured characters; this
script resolves each one to an existing Uma / SupportCard fixture row by name
and creates the join records.

Matching rules (mirrors update_fixture_images.py / fix_banner_support_links.py):
  - Featured Umas resolve by card_id: the sheet token ("Name (Version)") is
    matched to a card in character_cards.json, then that card_id is matched to
    the Uma fixture row via its image filename. This is robust to the fixture's
    display-name quirks (e.g. the base Jungle Pocket Uma is stored as
    "Jungle Pocket (Rerun)"), which pure name-matching can't handle.
  - Support cards resolve by normalized name (they carry no card_id in the
    sheet), with "(Rerun)" stripped and a short ALIASES map for sheet spellings
    that differ from the fixture ("Tamano Cross" -> "Tamamo Cross",
    "Tazuna" -> "Tazuna Hayakawa").
  - The anniversary "all-featured" banners scatter versions as separate "+"
    tokens. An orphan "(Version)" completes a preceding *bare* name into one
    unit ("Oguri Cap + (Christmas)" -> "Oguri Cap (Christmas)"), but starts a
    *new* unit when the preceding name already has a version
    ("Gold Ship (Summer) + (Project L'Arc)" -> two Gold Ship units).

Characters with no fixture row (their card image isn't in the Space yet, e.g.
Lucky Lilac, Admire Groove) are reported and simply left off that banner — the
banner is still created with whoever resolved, which is strictly better than an
empty row. Re-run add_missing_umas.py after uploading those images, then re-run
this to complete them.

Idempotent: only timelines that currently have NO uma and NO support banner are
processed, so re-running never duplicates.

Run from backend/ (dry-run prints the plan):
    python scripts/build_missing_banners.py
Apply:
    python scripts/build_missing_banners.py --apply
"""

import csv
import json
import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "calculatorapi" / "fixtures"
CSV_PATH = Path(__file__).parent / "data" / "timeline_master.csv"

BT_PATH = FIXTURES / "bannerTimelines.json"
BU_PATH = FIXTURES / "bannerUmas.json"
BS_PATH = FIXTURES / "bannerSupports.json"
UOB_PATH = FIXTURES / "umasOnUmaBanner.json"
SOB_PATH = FIXTURES / "supportsOnSupportBanner.json"
UMAS_PATH = FIXTURES / "umas.json"
SC_PATH = FIXTURES / "supportCards.json"
CARDS_PATH = Path(__file__).parent / "data" / "character_cards.json"

CARD_ID_RE = re.compile(r"(\d{6})-")

TARGET_PKS = set(range(149, 197))

# Sheet spelling -> fixture spelling. Kept tiny and explicit on purpose.
ALIASES = {
    "tamano cross": "tamamo cross",
    "tazuna": "tazuna hayakawa",
}


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[.'’♡♥❤♪&]", " ", s)
    s = re.sub(r"[-_]", " ", s)
    s = re.sub(r"\b3\d{4}\b", " ", s)  # drop embedded support game ids
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_rerun(s: str) -> str:
    return re.sub(r"\s*\(rerun\)\s*", " ", s, flags=re.I).strip()


def base_name(token: str) -> str:
    """'Gold Ship (Summer)' -> 'Gold Ship'; 'Oguri Cap' -> 'Oguri Cap'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", token).strip()


def has_version(token: str) -> bool:
    return bool(re.search(r"\([^)]*\)\s*$", token))


def split_features(cell: str) -> list[str]:
    """Split a 'A + B + C' banner cell into character tokens.

    An orphan '(Version)' token completes a preceding *bare* name into a single
    unit, but starts a *new* unit (base name + that version) when the preceding
    token already carries a version."""
    raw = [t.strip() for t in cell.split(" + ") if t.strip()]
    out: list[str] = []
    for tok in raw:
        if re.fullmatch(r"\([^)]*\)", tok) and out:
            if has_version(out[-1]):
                out.append(f"{base_name(out[-1])} {tok}")
            else:
                out[-1] = f"{out[-1]} {tok}"
        else:
            out.append(tok)
    return out


def parse_token(token: str) -> tuple[str, str]:
    """'Rice Shower (Halloween)' -> ('Rice Shower', 'Halloween'); a bare name or
    a '(Rerun)' qualifier -> ('Name', 'Original')."""
    m = re.search(r"\(([^)]*)\)\s*$", token)
    if m and m.group(1).strip().lower() != "rerun":
        return token[: m.start()].strip(), m.group(1).strip()
    return base_name(token), "Original"


def main() -> None:
    apply = "--apply" in sys.argv

    bt = load(BT_PATH)
    bu = load(BU_PATH)
    bs = load(BS_PATH)
    uob = load(UOB_PATH)
    sob = load(SOB_PATH)
    umas = load(UMAS_PATH)
    sc = load(SC_PATH)
    cards = load(CARDS_PATH)

    # Uma resolution: token -> card_id (character_cards) -> Uma fixture pk (image).
    cardid_by_charver = {}
    for c in cards:
        cardid_by_charver[(norm(c["name_en"]), norm(c.get("version_en") or "original"))] = c["card_id"]
    umapk_by_cardid = {}
    for r in umas:
        m = CARD_ID_RE.search(r["fields"]["image"] or "")
        if m:
            umapk_by_cardid.setdefault(int(m.group(1)), r["pk"])

    def resolve_uma(token: str):
        name, version = parse_token(token)
        card_id = cardid_by_charver.get((norm(name), norm(version)))
        if card_id is None:
            return None
        return umapk_by_cardid.get(card_id)

    # Support resolution: normalized name (lowest game_id wins on collisions).
    sup_by_norm: dict[str, tuple[int, int]] = {}
    for r in sc:
        k = norm(r["fields"]["name"])
        gid = r["fields"].get("game_id") or 0
        if k not in sup_by_norm or gid < sup_by_norm[k][0]:
            sup_by_norm[k] = (gid, r["pk"])

    def resolve_sup(token: str):
        for cand in (token, strip_rerun(token)):
            k = norm(cand)
            k = ALIASES.get(k, k)
            if k in sup_by_norm:
                return sup_by_norm[k][1]
        return None

    # timelines that already have banners must be left alone
    has_uma = {r["fields"]["banner_timeline"] for r in bu}
    has_sup = {r["fields"]["banner_timeline"] for r in bs}

    # map (jp_start, normalized name) -> timeline pk
    tl_by_key = {}
    # Fallback for placeholder-named timelines (e.g. "Support Only") whose
    # fixture name matches neither the sheet's uma nor support cell: map by
    # (jp_start, jp_end), but only for TARGET timelines and only when those
    # dates are unique among targets, so the summary-banner date collisions
    # (which already resolve by name) are never mis-mapped.
    tl_by_dates = {}
    date_dupes = set()
    for r in bt:
        f = r["fields"]
        jp = (f.get("jp_start_date") or "")[:10]
        tl_by_key[(jp, norm(f["name"]))] = r["pk"]
        if r["pk"] in TARGET_PKS:
            dkey = (jp, (f.get("jp_end_date") or "")[:10])
            if dkey in tl_by_dates:
                date_dupes.add(dkey)
            tl_by_dates[dkey] = r["pk"]
    for dkey in date_dupes:
        tl_by_dates.pop(dkey, None)

    rows = list(csv.reader(CSV_PATH.open(encoding="utf-8-sig")))

    next_bu = max((r["pk"] for r in bu), default=0)
    next_bs = max((r["pk"] for r in bs), default=0)
    next_uob = max((r["pk"] for r in uob), default=0)
    next_sob = max((r["pk"] for r in sob), default=0)

    created_bu = created_bs = links_u = links_s = 0
    unresolved = []
    plan = []

    for row in rows[1:]:
        if len(row) < 10:
            continue
        btype, pvp = row[6].strip(), row[7].strip()
        if btype == "-1" or pvp.startswith("CM") or pvp.startswith("LoH"):
            continue
        jp = row[0].strip()[:10]
        jp_end = row[1].strip()[:10]
        uma_cell, sup_cell = row[8].strip(), row[9].strip()

        pk = (tl_by_key.get((jp, norm(uma_cell)))
              or tl_by_key.get((jp, norm(sup_cell)))
              or tl_by_dates.get((jp, jp_end)))
        if pk not in TARGET_PKS:
            continue

        touched = False

        # Uma side — create the BannerUma only if the timeline lacks one AND at
        # least one featured Uma resolves. A side where nothing resolves (all
        # characters still missing their Space image) is left uncreated so a
        # later run completes it once the images/Uma rows exist.
        if uma_cell and pk not in has_uma:
            resolved = [(t, resolve_uma(t)) for t in split_features(uma_cell)]
            if any(u for _, u in resolved):
                next_bu += 1
                bu.append({"model": "calculatorapi.banneruma", "pk": next_bu,
                           "fields": {"banner_timeline": pk, "name": uma_cell,
                                      "admin_comments": "", "free_pulls": 0}})
                created_bu += 1
                touched = True
                for tok, upk in resolved:
                    if upk is None:
                        unresolved.append(("uma", pk, tok))
                        continue
                    next_uob += 1
                    uob.append({"model": "calculatorapi.umasonumabanner", "pk": next_uob,
                                "fields": {"banner_uma": next_bu, "uma": upk, "recommendation": None}})
                    links_u += 1
            else:
                for tok, _ in resolved:
                    unresolved.append(("uma", pk, tok))

        # Support side — same policy.
        if sup_cell and pk not in has_sup:
            resolved = [(t, resolve_sup(t)) for t in split_features(sup_cell)]
            if any(s for _, s in resolved):
                next_bs += 1
                bs.append({"model": "calculatorapi.bannersupport", "pk": next_bs,
                           "fields": {"banner_timeline": pk, "name": sup_cell,
                                      "admin_comments": "", "free_pulls": 0}})
                created_bs += 1
                touched = True
                for tok, spk in resolved:
                    if spk is None:
                        unresolved.append(("support", pk, tok))
                        continue
                    next_sob += 1
                    sob.append({"model": "calculatorapi.supportsonsupportbanner", "pk": next_sob,
                                "fields": {"banner_support": next_bs, "support_card": spk, "recommendation": None}})
                    links_s += 1
            else:
                for tok, _ in resolved:
                    unresolved.append(("support", pk, tok))

        if touched:
            plan.append(f"pk={pk}: {uma_cell or sup_cell!r}")

    print(f"Timelines processed: {len(plan)}")
    print(f"BannerUma created: {created_bu} ({links_u} uma links)")
    print(f"BannerSupport created: {created_bs} ({links_s} support links)")
    print(f"\nUnresolved tokens ({len(unresolved)}) — left off their banner (need a fixture row / Space image):")
    for kind, pk, tok in unresolved:
        print(f"  [{kind:7s}] pk={pk}: {tok}")

    if apply:
        BU_PATH.write_text(json.dumps(bu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        BS_PATH.write_text(json.dumps(bs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        UOB_PATH.write_text(json.dumps(uob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        SOB_PATH.write_text(json.dumps(sob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("\nAPPLIED: wrote bannerUmas, bannerSupports, umasOnUmaBanner, supportsOnSupportBanner.")
    else:
        print("\nDRY RUN — re-run with --apply to write fixtures.")


if __name__ == "__main__":
    main()
