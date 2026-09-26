# Wikipedia — Robert "Bob" Tann

> Status index. Convention per [#73](https://github.com/biofool/story_graph/issues/73):
> 3 maintained files per subject — this index, `-wikimarkup.md`, `-talk.md`.
> Only the index exists for this subject: assessment is **no standalone
> article**, so there is no draft to maintain.
> Pipeline v2 (#80): `data/wikipedia-updates/<slug>.json` is now the
> decision record; `rendered/<slug>{,-wikimarkup,-talk}.md` are the generated
> views (scripts/61_render_wikipedia_updates.py). This file is frozen pending
> review that the rendered views cover it.

## Open action items

- **No standalone article is warranted** — sourcing is a single
  Encyclopedia of Aikido entry plus two comment-section reminiscences
  (Naughton-Wright 2011, Kemp 2013). That is not significant coverage;
  GNG fails as it stands.
- **His citable home is inside Nadeau's article** — see proposed
  sentence below.
- **If more coverage surfaces**, reopen the assessment: *Aikido Today
  Magazine* archives, South San Francisco PD records/clippings,
  Marin/SSF newspaper obituaries (d. 26 Jan 2001), and the Nadeau
  biography *Aikido: The Art of Transformation* (2024, six student
  co-authors) likely all discuss him.
- **Graph hygiene done** — `person:bob-tann` and the malformed
  `person:aikikai-hombu-dojo-bob-tann` (spaCy junction artifact) are
  `ALIAS_OF` `person:robert-tann`; nodes retained for provenance.

## Status

- **Live article**: none — checked 2026-09-26 (enwiki search returns
  nothing relevant).
- **Mode**: none — no draft proposed. Notability assessment below is an
  internal finding, not a submission position.

## Who he is (graph record)

Robert Tann (1931 – 26 January 2001). US Marine Corps veteran; police
officer on the South San Francisco Police Department. Early Northern
California aikido pioneer; taught aikido in South San Francisco
1960–1972. **Among his students was Robert Nadeau** — i.e., Nadeau's
pre-Japan aikido teacher, which is why he matters to this project.

Consistent with Nadeau's timeline: Nadeau "began practice in the late
1950s" and spent 2+ years at Aikikai Hombu in the early 1960s (AJ
Encyclopedia); Tann's SSF teaching window (1960–72) covers the pre-Japan
period, and Bob Noha recounts the Mountain View dojo writing the
Aikikai for an instructor — Nadeau arrived dispatched "fresh from
Japan" ~1966.

Comment-section texture (not citable, but first-person): Rocky Kemp
trained under Tann 1958–59 at MCRD San Diego (Tann was SSgt in the
self-defense section; CO was MSgt B.J. Carlisle); Noreen Naughton
Wright's father Edward Naughton was Tann's first SSF student in 1962;
Tann retired on medical grounds after a police-duty crash.

## Proposed addition — inside Robert Nadeau (aikidoka), Early life

```wikitext
Before travelling to Japan, Nadeau studied aikido under Robert Tann, a
Marine Corps veteran and South San Francisco police officer who taught
aikido in South San Francisco from 1960 to 1972.<ref>{{cite
 encyclopedia |title=Robert Tann |encyclopedia=Encyclopedia of Aikido
 |publisher=Aikido Journal |date=2011-08-27
 |url=https://aikidojournal.com/2011/08/27/robert-tann/
 |access-date=2026-09-26}}</ref>
```

This sentence is strictly what the source says — the encyclopedia entry
names Nadeau among Tann's students and gives the dates. It does not
claim Tann was Nadeau's *first* or *only* teacher (the late-1950s start
predates the documented SSF window), and it does not assert a dojo
affiliation beyond the published record.

## Sources

| Source | Class | What it carries |
|---|---|---|
| [Encyclopedia of Aikido — Robert Tann](https://aikidojournal.com/2011/08/27/robert-tann/) | journalistic (edited reference) | dates, Marine/SSF-PD background, taught 1960–72, Nadeau among students |
| [AJ — Robert Nadeau](https://aikidojournal.com/2011/08/27/robert-nadeau/) | journalistic (edited reference) | Nadeau timeline corroboration (late-1950s start, Hombu early '60s) |
| Comment: Noreen Naughton Wright (2011) | comment_thread | father was Tann's first SSF student, 1962 — corroborating lead only |
| Comment: Rocky Kemp (2013) | comment_thread | trained under Tann at MCRD San Diego 1958–59 — corroborating lead only |

## Why no standalone article

- One reference-entry + two blog comments is not "significant coverage
  in reliable independent sources."
- No independent journalism located; not checked exhaustively — the
  action items list the plausible archives.
- If *Aikido Today* or the Nadeau biography give him real coverage, the
  assessment can be revisited.
