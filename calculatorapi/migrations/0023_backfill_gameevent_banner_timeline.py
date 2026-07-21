from django.db import migrations

# Built by scripts/map_events_to_banner_timelines.py from a user-supplied
# "Timeline Master" CSV export, joined against bannerTimelines.json on
# (JP Start Date, name). 182 of 200 GameEvent rows matched a BannerTimeline;
# the remaining 18 are intentionally omitted (left unlinked) -- 14 are
# Champions-Meeting-tie-in placeholders ("Champions Meeting 2027-01-13" etc,
# which never derive from a banner), 3 are unbuilt future placeholders
# ("Event 2029-01-XX"), and 1 has a truncated/mangled name with no clean
# match in either dataset.
GAME_EVENT_BANNER_TIMELINE_MAP = {
    1: 149, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10,
    12: 11, 13: 12, 14: 13, 15: 14, 16: 15, 17: 16, 18: 17, 19: 18, 20: 19,
    21: 20, 22: 21, 23: 22, 24: 23, 25: 24, 26: 25, 27: 26, 28: 27, 29: 28,
    30: 29, 31: 30, 32: 31, 33: 32, 34: 33, 35: 34, 36: 35, 37: 36, 38: 37,
    39: 38, 40: 39, 41: 40, 42: 41, 43: 42, 44: 43, 45: 44, 46: 45, 47: 46,
    48: 47, 49: 48, 50: 49, 51: 50, 52: 51, 53: 52, 54: 53, 55: 54, 56: 55,
    57: 56, 58: 57, 59: 58, 60: 59, 61: 57, 62: 61, 63: 62, 64: 63, 65: 64,
    66: 65, 67: 66, 68: 67, 69: 68, 70: 69, 71: 70, 72: 71, 73: 72, 74: 150,
    75: 73, 76: 74, 77: 75, 78: 76, 79: 77, 80: 78, 81: 79, 82: 151, 83: 80,
    85: 81, 86: 82, 87: 83, 88: 84, 89: 85, 90: 86, 92: 87, 93: 88, 94: 152,
    95: 89, 96: 90, 97: 91, 99: 92, 100: 93, 102: 94, 103: 95, 104: 96,
    106: 97, 107: 98, 108: 154, 109: 99, 110: 100, 111: 155, 113: 101,
    114: 102, 115: 156, 116: 103, 117: 157, 118: 104, 119: 105, 120: 106,
    121: 158, 122: 107, 123: 159, 124: 108, 126: 160, 127: 109, 128: 161,
    129: 110, 130: 111, 131: 162, 133: 112, 134: 113, 135: 114, 136: 115,
    137: 116, 138: 163, 140: 117, 141: 164, 142: 118, 143: 119, 144: 165,
    146: 120, 147: 121, 148: 166, 149: 122, 150: 123, 151: 167, 152: 124,
    153: 168, 155: 125, 156: 126, 157: 169, 158: 127, 159: 128, 160: 170,
    161: 129, 162: 171, 163: 130, 164: 172, 166: 131, 167: 173, 168: 132,
    169: 133, 170: 174, 171: 134, 172: 175, 174: 135, 175: 136, 176: 137,
    177: 176, 178: 138, 179: 139, 180: 177, 181: 140, 182: 141, 183: 142,
    184: 178, 186: 143, 187: 144, 188: 179, 189: 145, 190: 180, 191: 181,
    192: 146, 193: 182, 194: 147, 195: 183, 197: 148,
}


def forwards(apps, schema_editor):
    GameEvent = apps.get_model("calculatorapi", "GameEvent")
    rows = list(GameEvent.objects.filter(pk__in=GAME_EVENT_BANNER_TIMELINE_MAP))
    for row in rows:
        row.banner_timeline_id = GAME_EVENT_BANNER_TIMELINE_MAP[row.pk]
    if rows:
        GameEvent.objects.bulk_update(rows, ["banner_timeline_id"])


def backwards(apps, schema_editor):
    GameEvent = apps.get_model("calculatorapi", "GameEvent")
    GameEvent.objects.filter(pk__in=GAME_EVENT_BANNER_TIMELINE_MAP).update(banner_timeline_id=None)


class Migration(migrations.Migration):
    """Backfills banner_timeline on existing GameEvent rows using a mapping
    derived from a user-supplied CSV (see scripts/map_events_to_banner_timelines.py).
    Rows not in the map stay unlinked -- they don't correspond to a single
    banner (Champions Meeting tie-ins, unbuilt placeholders, one mangled name)."""

    dependencies = [
        ("calculatorapi", "0022_gameevent_banner_timeline"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
