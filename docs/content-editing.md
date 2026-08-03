# Content Editing Guide

How to manage the game data behind the Uma Musume Carat Calculator through the
admin site. Written for content editors — no technical background needed.

## Logging in

Go to `https://<your-domain>/admin/` and sign in with the staff account you
were given. You'll land on the **Dashboard**, which shows a few headline usage
numbers at the top and a **Reports** card linking to the analytics dashboard.

Everything you can edit is grouped in the left sidebar into sections —
**Banners**, **Events & competitions**, **Characters**, **Income tables**,
**Site content**, and **Users & access**. Click a section heading to expand or
collapse it. The light/dark theme toggle is in the sidebar next to your account
name.

You will only see the models you have permission to edit. User accounts and
players' saved plans are managed separately and never appear in your view.

## The banner structure

Banners are organized in three levels:

1. **Banner timeline** — the date window a set of banners runs in (e.g.
   "Almond Eye", July 10–20). Has a name, start/end dates, and an image.
2. **Uma banner / Support card banner** — the actual gacha banners inside a
   timeline. Each has a name and the number of **free pulls** it grants
   (the calculator counts these toward what players can afford).
3. The **umas / support cards featured on the banner**, each with an optional
   recommendation text.

### Adding a new banner, start to finish

1. **Banners → Timelines → Add**. Fill in the name, dates, and
   image, then **Save and continue editing**.
2. Still on the timeline page, add rows under **Uma banners** and/or
   **Support card banners** (name + free pulls). Save.
3. Click the **Change** link next to a banner row to open the banner's own
   page. Under **Umas on banner** (or **Support cards on banner**), pick each
   featured uma/card — start typing a name and the box searches for you — and
   optionally add a recommendation. Save.

If a featured uma or card doesn't exist yet, create it first under **Umas** /
**Support cards** (name + image), or use the green **+** next to the picker.

### Confirmed vs. predicted dates

A row's **JP server dates** are always filled in; the **global server dates**
stay blank until the event is officially confirmed — until then the site shows
players dates *predicted* from the JP schedule. The list shows each row's state
as a **Confirmed** (green) or **Predicted** (amber) badge, and the **Global
dates** filter in the sidebar lists everything still awaiting confirmation, so
you can spot what needs dates filled in.

This same JP/Global date system applies to **banner timelines, Champions
Meetings, and League of Heroes events** — all three have split JP/Global date
sections, the Confirmed/Predicted badge, and the Global dates filter.

### Fixing predicted dates when global falls behind schedule

Predictions assume global keeps working through JP's back-catalogue at a steady
pace. When it doesn't — a banner gets delayed, a break week gets inserted —
every predicted date after that point is wrong by the same number of days.

The **Schedule offset (advanced)** box on each row is the fix. Set it on the one
row where the delay starts, and:

- **that row moves forward by that many days**, and
- **so does every later banner, Champions Meeting and League of Heroes event.**

⚠️ **This is not a local edit.** One offset moves a large part of the calendar.
That is the whole point — a one-week delay really does push everything after it
back a week — but it means you should only reach for it when global's schedule
has genuinely slipped, not to nudge a single row you think looks wrong.

You can set more than one, and they add up. If you set **+7** on a banner in
August and later set **+3** on an event in September, everything from September
onward moves **10** days.

Two things that keep this safe:

- **It only affects predicted rows.** Once a row's global dates are confirmed,
  its offset stops doing anything — both to itself and to the rows after it.
  Confirmed dates are facts and are never moved.
- **You don't have to clean up after yourself.** When a delayed banner is finally
  confirmed, its offset switches itself off, and the rows after it start
  predicting from that banner's real date instead. The list shows a leftover
  value as *"+7d (inactive)"* so you can tell it's no longer doing anything.

The **Offset** column shows which rows are carrying one, and the **Schedule
offset** filter in the sidebar lists them all — the quickest way to see what is
currently shifting the calendar. To undo an offset, set it back to `0`.

You can also enter a negative number to pull dates *earlier*, if global gets
ahead rather than behind.

### Seeing which banners players care about

The Uma banner and Support card banner lists have a **Planned by** column —
how many players currently have that banner in their pull plan. Click the
column header to sort by it.

## Events

**Game events** hold an event's name, dates, and image; its **reward amounts**
(carats, tickets, shards, crystals) are edited directly on the same page, under
a **Rewards** section. There are two carat fields:

- **Carat amount** — paid out in full as soon as the event starts (along with
  every ticket/shard/crystal field on the page).
- **Carats throughout** — spread evenly across the whole event's run instead of
  paid all at once, for campaigns that trickle out carats day by day rather than
  granting them in one lump.

Both directly affect players' projections, so keep the amounts accurate to the
in-game event.

## Changelog (patch notes)

**Changelog entries** are the update notes shown on the public Changelog page.
Each entry has a **title**, a **date**, and an optional **version** label (e.g.
`v1.2` — leave it blank if you don't use versions). The individual update lines
are edited in the table at the bottom of the entry's page: give each line a
**category** (Added / Fixed / Changed), the **text** of the change, and an
**order** number (lower numbers show first). Entries appear newest-first on the
site, and the home page shows how long ago the most recent entry was posted.

## Champions Meetings & League of Heroes

- **Champions Meetings**: the form is grouped into basic info, **JP / Global
  server dates** (see *Confirmed vs. predicted dates* above), **Track details**
  (surface, distance, weather, …) and **Stat recommendations**. Recommended umas
  are added at the bottom of the page with a search picker.
- **League of Heroes events**: name, **JP / Global server dates** (same
  Confirmed/Predicted system), and image.

## Rank tables

**Club ranks, Team trials ranks, Champions Meeting ranks, League of Heroes
ranks** define how many carats (and tickets/shards, where applicable) players
earn per rank. The amounts are edited directly in the list — change as many
rows as you need, then press **Save** once at the bottom. Only change these
when the game itself rebalances payouts — they feed every player's income
projection.

## Images

Anywhere you see an **Image** field, you have two ways to fill it:

- **Upload a new file** — use the upload box exactly as before. The file is
  stored automatically; you don't need to put it anywhere yourself first.
- **Choose from library** — click this button to browse every image already
  on the site. Search by file name, or switch folders (umas, support cards,
  banner timelines, …) with the dropdown to reuse an image from a different
  section — handy when an event or Champions Meeting should carry the same
  artwork as its banner.

Picking from the library does **not** make a second copy, so reusing one image
in several places is free and stays consistent everywhere it appears.

A few things worth knowing:

- If you pick from the library and upload a file in the same edit, the
  **uploaded file wins**. Use **Undo** next to the selection if you change
  your mind before saving.
- The library list is remembered for a few minutes for speed. If you just
  uploaded something in another tab and don't see it yet, press the **refresh**
  icon at the top of the picker.
- If the picker says it can't load the library, the site can still upload
  files normally — tell the site owner, it means the image storage is
  unreachable.

## A few care notes

- **Deleting a timeline deletes its banners**, and deleting a banner removes
  it from any player's saved plan. Prefer editing over deleting.
- Dates are stored with timezones; keep the same convention as existing
  entries (UTC).
- "Admin comments" fields are notes for editors.

---

## For the site owner (technical setup)

Creating a content-editor account:

1. Make sure the permission group exists — run once per environment:
   ```bash
   python manage.py create_content_editor_group
   ```
   (In production: DigitalOcean → API component → Console tab.)
2. In the admin as a superuser: **Users → Add** → set username/password →
   on the next screen check **Staff status** and add the **Content editors**
   group → Save.

The group grants add/change/delete/view on all game content and rank tables,
and nothing else. Rerunning the command is safe — it resets the group's
permissions to exactly the intended set (see
`calculatorapi/management/commands/create_content_editor_group.py`).
