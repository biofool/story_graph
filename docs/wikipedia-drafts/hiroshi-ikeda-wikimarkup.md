# Hiroshi Ikeda — proposed update (wikimarkup)

> Proposed additions/repairs for the live article
> [Hiroshi Ikeda (aikidoka)](https://en.wikipedia.org/wiki/Hiroshi_Ikeda_(aikidoka))
> (snapshot: revid 1376549637, 2026-09-25).
>
> Do NOT edit Wikipedia directly without operator approval (PRD Appendix C).

## Open action items

- Aikido Bridge sentence — **affiliated sources only**; attribution
  used, editors judge.
- Live-article repairs: empty `[[ ]]` link; "based in the Boulder, CO".
- "Scheduled seminars" staleness — dated-update convention needed.
- Hawaii (Floating Bridge / Ka'u Aikikai) seminars — **not citable
  yet**; pending published announcements/flyers.
- "Visited frequently" dojo edges — leads, not affiliations; excluded.
- Ingest the live article's 3 Newspapers.com seminar citations into the
  graph (Missoulian 1982, Bradenton 1991, Pensacola 2000).

## Proposed additions

### 1. Aikido Bridge (new sentence, end of career paragraph)

The live article links the International Aikido Friendship Seminar in
External links but never explains Aikido Bridge — Ikeda's most notable
organizational initiative after Boulder Aikikai. Sources are affiliated
(the series' own site + Ikeda's site) — proposed **with attribution**
per WP:ABOUTSELF; whether that suffices is an editor question.

```wikitext
In 2005, Ikeda started the Aikido Bridge seminar series, which brings
together teachers and students from different aikido organizations; the
series began with the "Un Pont" International Friendship Seminar held
at Jiai Aikido in San Diego.<ref name="aikidobridge">{{cite web
 |title=About Bridge Events |work=Aikido Bridge
 |url=http://aikidobridge.com/about/ |access-date=2026-09-25}}</ref><ref
name="ikeda-bridge">{{cite web |title=Aikido Bridge
 |work=Hiroshi Ikeda Shihan (official site)
 |url=https://www.hiroshi-ikeda.com/aikido-bridge |access-date=2026-09-25}}</ref>
```

### 2. Live-article repairs (minor)

```wikitext
— In 1980, Ikeda moved to Boulder, Colorado, where he established [[ ]]
  under Saotome's ASU organization.
+ In 1980, Ikeda moved to Boulder, Colorado, where he established
  Boulder Aikikai under Saotome's ASU organization.

— based in the Boulder, CO
+ based in Boulder, Colorado
```

### 3. "Scheduled seminars" maintenance (propose on talk)

The section is dated "As of 17 September 2026" and will silently go
stale. Options for editors: date-stamp it explicitly, or convert to a
single sentence noting that Boulder Aikikai publishes the schedule
(already cited). Not edited by us.

## Explicitly NOT proposed

| Material | Graph status | Why excluded |
|---|---|---|
| Hawaii seminars — Floating Bridge / Ka'u Aikikai, Big Island (2024–2026; Jan 2027 planned) | Bob Klein (Aikido of Hilo) personal email, 2026-09-25 | Personal communication — not a published source. Becomes citable if the dojo publishes announcements or flyers (2024/2025 flyers exist per Klein; Gary Reiss outreach pending). |
| "Schools he visited frequently" — Harmonie Club 87 (Limoges), Instituto Takemussu (São Paulo), Two Cranes Aikido, and similar | Outreach lead edges (`DOJO_AFFILIATION` pending confirmation) | A visit ≠ an affiliation; must not be asserted (the Varjan incident — Kohala Aikikai's denial is preserved in the graph). Only includable if a published record of a specific seminar exists. |
| Seminar calendar data (docs.google.com published sheet) | Organizational data dump | Mirrors the Boulder Aikikai schedule already cited; not an independent source. |
| Kristina Varjan denial, Garth Jones reply, other email replies | `email://`/`kkron://` sources | Personal communication — graph evidence only. |
| 386 routine seminar listings | CO_APPEARANCE edges | The live article already carries a representative seminar list; bulk additions would be a directory, not prose. |

## Editorial notes

- **Graph gap**: the live article's Newspapers.com citations
  (Missoulian 1982-04-13 p.11; Bradenton Herald 1991-09-29 p.22;
  Pensacola News Journal 2000-09-30 p.34) are not in the graph —
  ingest candidates, useful corroboration for the seminar-history
  pattern.
- **Reliability report**: 0 RELIABLE sources in the Ikeda subgraph;
  every source is his own site, the Google-sheets calendar, or
  personal communication. The article's current sourcing (Pranin's
  Encyclopedia of Aikido + newspaper listings) is stronger than
  anything the graph can currently add.
- Compare report: 452 candidate additions, 0 citable uncited sources,
  4 heuristic date mismatches all false positives (2026 seminar rows
  sharing venue names with historical entries).
