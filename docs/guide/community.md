---
title: "Community"
description: "Comments with guest moderation and spam defences, a live forum, private messages, notifications and a near-me page."
---

# Community

These modules let visitors take part: comment, discuss, write to each other, and find
what is near them. Each is a standalone module, so a game, a magazine and a village site
use the same forum or comments, each in its own look.

## Comments

`comments` adds threaded comments to anything. The subject of a thread is a name,
not a foreign key (`"content.entry:12"`, `"gallery.collection:7"`), so any module's
records can be commented without the comments module knowing them.

```yaml
modules:
  - name: comments
    route: /comentarii
    config:
      allow_guests: true
```

A page embeds a thread in its template, only when the application has the module:

```html
{% if comments is defined %}{{ comments("content.entry:" ~ entry.id) }}{% endif %}
```

The content module's pages already do this.

### Who may comment, and who waits

| Setting | Default | Meaning |
|---|---|---|
| `allow_guests` | false | Whether people who have not signed in may comment |
| `moderation` | `guests` | Whose comments wait for a moderator: `none`, `guests` or `all` |
| `max_depth` | 3 | How deep replies nest; a deeper reply sits beside its parent |
| `min_seconds` | 3 | A form sent back sooner than this after it was shown is refused |
| `per_hour` | 10 | Comments a guest may send per address per hour |

Members with the `moderator` role are always published at once. Bodies are plain
text, shown with paragraphs, and links get `rel="nofollow ugc"`.

### Moderation

Moderators work at **Admin → Comments**: the comments waiting, those approved and
those marked spam, each changed with one click. The panel's home shows how many wait,
as a badge on the Comments tile.

### Spam defences

Robots meet several cheap checks before a comment is stored:

- **A signed subject.** The form carries the thread's subject signed with the site's
  key, so nobody can post to a thread a page did not offer.
- **A honeypot.** A field people cannot see; robots fill it, and are refused.
- **A minimum time.** A form sent back within `min_seconds` is refused.
- **A per-address limit** for guests (`per_hour`). The address is kept only as a
  keyed hash, never in clear.

Comments come in from old sites with `nest comments import-wordpress APP dump.sql`.
They are attached to the pages the old posts became, found through a lookup the content
module answers.

## Forum

`forum` has boards, topics and posts.

```sh
uv run nest forum add-board APP "General" --description "Anything about the site."
uv run nest forum add-board APP "Crafts" --parent general        # a board in a board
uv run nest forum boards APP
```

| Setting | Default | Meaning |
|---|---|---|
| `public_read` | true | Whether people who have not signed in may read |
| `posts_per_minute` | 5 | Posts a member may send per minute |
| `edit_minutes` | 30 | How long an author may edit a post |
| `topics_per_page`, `posts_per_page` | 30 | Paging |
| `public_names` | `known_as` | The names posts show on public boards: `known_as` (as the application names its people; a game, by their characters) or `account` (the account's own name, never its email) |

Posting is for members. Moderators pin, lock and hide in the topics themselves;
**Admin → Forum** shows the boards.

**Replies arrive live.** A new reply is pushed over Server-Sent Events to everyone
reading the topic, so it appears without a reload. Without JavaScript the form posts
and the page reloads at the new post.

### Boards in boards

Boards nest to any depth: a board's page lists the boards in it, then its own topics, with
the way back up above the title. The forum's index lists only the outer boards.
In **Admin → Forum**, moderators and administrators see every board as a tree and add a
board at the first level or inside any other; from a board's own page they add one inside
it (**Add a board here**); the command line takes `--parent`. A board made in another has its scope, so a private board's inner boards
have the same members, however deep.

### Archiving and deleting

In **Admin → Forum** each board can be opened (rename it, describe it, set its order),
**archived** or **deleted**; what is done to a board is done to every board in it.

- **Archived**: still read by those who may read it, written by no one (moderators
  included): no new topics, replies, edits or inner boards. It is listed apart, under
  **Archive**, below the open boards. Taking it out of the archive opens it again.
- **Deleted**: the board, every board in it, their topics and posts are gone. A page
  says first how many boards, topics and posts will go, and offers to archive instead.

Topics too: on a board's admin page, or with the moderation buttons in the topic,
a topic is archived (read only, listed under **Archived topics**) or deleted with its
posts. A private board deleted is made again, empty, the next time its members open it.

### Private boards

A board may have a **scope**, a string that says whose it is, such as
`club/team:12` (a team's own board). A scoped board:

- is never listed on the forum's index;
- is read and written only by those the application lets in. The forum asks the
  `forum.access` lookup, `{"user": id, "scope": "…"}`, and expects
  `{"read": bool, "post": bool}`. To anyone else, its pages, topics and live replies
  answer "not found", so a private board doesn't even show that it exists;
- shows posts under the names the application gives its people (`known_as`).

Moderators read and moderate every board. Another module has a scoped board made when it
is first wanted, through the `forum.board` lookup:

```python
board = host.lookup("forum.board", {"scope": "club/team:7", "title": "Echipa de juniori"})
# -> {"slug": "echipa-de-juniori", "url": "/forum/echipa-de-juniori/"}
```

The module that owns the scope answers `forum.access` and decides who its members are.

## Messages

`messages` holds private conversations between members.

| Setting | Default | Meaning |
|---|---|---|
| `max_recipients` | 10 | People one conversation may start with |
| `per_hour` | 60 | Messages a member may send per hour |

- **Privacy.** Members write to each other by email, or by name when it is
  unambiguous. Only participants see a conversation; anyone else gets a 404.
- **Live delivery.** Each member has their own channel that only they may follow. A
  new message appears in the open conversation and the inbox refreshes.
- **An unread badge.** A layout shows the unread count with
  `{% include "messages/badge.html" %}`.

## Notifications

`notifications` shows short messages, called toasts, after an action: "Saved.",
"Deleted.", "Sent.". It has no pages and needs no route:

```yaml
modules:
  - name: notifications
```

A module says `toast(request, _("Saved."))` whatever it answers next. After a
redirect, the message travels in a signed, short-lived cookie that the next page
reads once; in an htmx answer it goes in a header and shows at once. The messages are
read by screen readers too. Without this module, toasts are silently dropped, so
include it in any site with an admin panel.

## Near me

`geo` gives a near-me page: the reader shares their position, and the page shows
what every module has nearby. Any module takes part by answering the `geo.near`
lookup; `maps` (its markers) does.

```yaml
  - name: geo
    route: /in-apropiere
```

| Setting | Default | Meaning |
|---|---|---|
| `radius_km` | 50 | How far the page looks |
| `limit` | 10 | How many places of each kind it shows |

Only pages that ask for it may use the browser's position: every other page is
served with a Permissions-Policy that forbids it. Modules also get
`distance_km`, `box` and `near` from `nest_geo` for their own queries.
