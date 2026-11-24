<!-- nest:readme -->
# Ratings

Stars, useful-or-not and up/down votes on any module's records, anonymous and one per visitor.

**Version 0.1.0** · module · works with Nest `>=0.4.6,<1` · licence MIT

| | |
|---|---|
| package | `nest-rating` |
| name in a manifest | `rating` |
| category | community |
| reference | https://nest-framework.org/docs/reference/modules/rating |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: rating
    route: /rating
```

## Settings

| setting | kind | default |
|---|---|---|
| `min_votes` | int | `5` |
| `per_minute` | int | `10` |
| `schema` | bool | `True` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
## Using it in a page

```jinja
{% if rating is defined %}{{ rating("coaches.operator:" ~ slug, "stars", name=operator.name, item="Organization") }}{% endif %}
{{ rating("content.entry:" ~ entry.id, "helpful") }}
{{ rating("glossary.entry:" ~ e.id, "updown") }}
```

- **stars** (1–5): an average and the count, from `min_votes` votes; the distribution in
  the admin panel.
- **helpful** (yes / no): the share of yes. The same button again takes the vote back.
- **updown** (▲ / ▼): a score, for sorting.

The subject is a name (`module.kind:id`), not a foreign key: any module's records can be
rated without this module knowing them. The form carries the subject signed, so nobody can
vote on one a page did not offer. `item` (a schema.org type: `Organization`,
`LocalBusiness`, `Product`...) writes the stars as AggregateRating for search engines,
from `min_votes` votes; leave it out for things search engines do not rate (stations,
stops).

Summaries for lists and sorting: `host.lookup("rating.summary", subject)`,
`host.lookup("rating.summaries", [subjects])`.

## Keeping it honest

- One vote per visitor and subject, changeable: a random voter id in the `nest_voter`
  cookie (necessary, set only when voting; on the cookies page), and a day's hash of the
  address and browser: up to 3 votes a day on one subject count apart from one address
  and browser (a few people share a mobile network's address, and browsers look alike);
  beyond, clearing the cookie again only changes the latest vote. Neither the address nor
  the browser string is kept. A signed-in visitor votes as themselves.
- `per_minute` votes per address; an average only from `min_votes` votes.
- The admin panel: the subjects lately rated (close voting, reset), and the visitors with
  many votes in a day (forget all their votes, recounted).
