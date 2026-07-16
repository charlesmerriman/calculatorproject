# Content Editing Guide

How to manage the game data behind the Uma Musume Carat Calculator through the
admin site. Written for content editors — no technical background needed.

## Logging in

Go to `https://<your-domain>/admin/` and sign in with the staff account you
were given. You'll land on **Content management**, which lists everything you
can edit under **Uma Musume Data**, plus a **Reports** box linking to the
analytics dashboard.

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

1. **Uma Musume Data → Banner timelines → Add**. Fill in the name, dates, and
   image, then **Save and continue editing**.
2. Still on the timeline page, add rows under **Uma banners** and/or
   **Support card banners** (name + free pulls). Save.
3. Click the **Change** link next to a banner row to open the banner's own
   page. Under **Umas on banner** (or **Support cards on banner**), pick each
   featured uma/card — start typing a name and the box searches for you — and
   optionally add a recommendation. Save.

If a featured uma or card doesn't exist yet, create it first under **Umas** /
**Support cards** (name + image), or use the green **+** next to the picker.

## Events

**Game events** hold an event's name, dates, and image; its dated **reward
entries** (carats, tickets, shards, crystals) are edited in the table at the
bottom of the same page. The calculator pays players these rewards on the
dates you enter, so the amounts and dates directly affect projections.

## Champions Meetings & League of Heroes

- **Champions Meetings**: the form is grouped into basic info, **Track
  details** (surface, distance, weather, …) and **Stat recommendations**.
  Recommended umas are added at the bottom of the page with a search picker.
- **League of Heroes events**: name, dates, and image.

## Rank tables

**Club ranks, Team trials ranks, Champions Meeting ranks, League of Heroes
ranks** define how many carats (and tickets/shards, where applicable) players
earn per rank. Only change these when the game itself rebalances payouts —
they feed every player's income projection.

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
