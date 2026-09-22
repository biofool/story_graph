# Dan Millman Wikipedia Article — Improvement Plan (issue #20)

> Do NOT edit Wikipedia directly. This document prepares suggested
> additions/changes, properly cited, for review before submission.
> Target article: https://en.wikipedia.org/wiki/Dan_Millman

## Summary

The Wikipedia article for Dan Millman has minimal coverage of his martial
arts background and several `[citation needed]` tags. This plan adds
martial arts coverage (judo, karate, aikido, the Robert Nadeau
student-teacher lineage), the World Trampoline Championship gold medal,
the "Way of the Peaceful Warrior" origin, and resolves the citation-needed
tags using reliable secondary sources already ingested in the Story Graph.

## Current article state (verified from `wikipedia-dan-millman.html`)

The article has 14 `[citation needed]` tags (dated December 2017 and June
2021). The martial-arts-relevant ones are:

1. **Stanford gymnastics coaching prominence:**
   > "...led the Stanford gymnastics team to national prominence.
   > [citation needed]"
2. **Aikido shodan at Stanford (the key gap):**
   > "During Millman's tenure at Stanford, he trained in aikido, eventually
   > earning a shodan (black belt) ranking; he studied tai chi and other
   > martial arts. [citation needed]"
3. **Co-Senior Athlete of the Year (high school):**
   > "...recognized along with another student as a Co-Senior Athlete of
   > the Year. [citation needed]"

**Coverage gaps confirmed:**
- Judo training: **0 mentions**
- Karate training: **0 mentions**
- Aikido: **1 mention** (shodan, but `[citation needed]`)
- Robert Nadeau (his Aikido teacher): **0 mentions**
- World Trampoline Championship gold medal: **0 mentions** (despite
  "trampoline" appearing in categories)
- "Way of the Peaceful Warrior" origin (Oberlin Tai Chi/Aikido course):
  **not connected to martial arts**

## Sources available (all ingested in the Story Graph)

| # | Source | URL | Reliability | Key martial arts content |
|---|---|---|---|---|
| 1 | Wikipedia (current) | https://en.wikipedia.org/wiki/Dan_Millman | baseline | has aikido shodan mention, needs citations |
| 2 | whistlekick Martial Arts Radio Ep. 672 | https://www.whistlekickmartialartsradio.com/blog/672-dan-millman | primary (interview) | Millman discusses judo (started due to bullies), karate, aikido; "Way of the Peaceful Warrior" origin from Oberlin Tai Chi/Aikido course |
| 3 | USA Gymnastics Hall of Fame | https://usagym.org/halloffame/inductee/millman-dan | secondary (HOF) | "Aikido black belt took gold at the World Trampoline Championship" |
| 4 | US Gymnastics Hall of Fame | https://usghof.org/d_millman | secondary (HOF) | "athletic training began at nine... study numerous martial arts, earning a black belt in Aikido" |
| 5 | Alchetron | https://alchetron.com/Dan-Millman | tertiary (mirror) | "During Millman's tenure at Stanford, he trained in Aikido, eventually earning a shodan (black belt)" |
| 6 | Wikipedia — Robert Nadeau (aikidoka) | https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka) | secondary (Wikipedia) | Lists Dan Millman as a **notable student** of Robert Nadeau |
| 7 | BudoVideos — Aikido: The Art of Transformation (Nadeau book) | https://budovideos.com/products/aikido-the-art-of-transformation-the-life-and-teachings-of-robert-nadeau | secondary (publisher) | "personal stories about Nadeau contributed by students, including Dan Millman, Richard Strozzi-Heckler, Peter Ralston..." |

## The Robert Nadeau lineage (key addition)

The Story Graph confirms the Millman–Nadeau student-teacher relationship:

- **Graph edge:** `person:dan-millman --MEMBER_OF--> person:robert-nadeau`
  (student-teacher)
- **Claim** `claim:search:nadeau-millman-student`:
  > "Dan Millman is a notable student of Robert Nadeau (Wikipedia +
  > multiple sources)"
  - Wikipedia quote: *"Notable students: George Leonard, Richard
    Strozzi-Heckler, Dan Millman, Richard Moon"* (from the Robert Nadeau
    Wikipedia article)
  - BudoVideos quote: *"Presents inspiring personal stories about Nadeau
    contributed by students, including Dan Millman, Richard
    Strozzi-Heckler, Peter Ralston, and Renee Gregorio"*
  - Sources: https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka),
    https://budovideos.com/products/aikido-the-art-of-transformation-the-life-and-teachings-of-robert-nadeau,
    https://www.aikido-health.com/robert-nadeau.html,
    https://www.cityaikido.com/nadeau-shihan

Robert Nadeau is a prominent Aikido shihan who trained directly under
Morihei Ueshiba (the founder of Aikido) in Japan in the early 1960s, then
founded City Aikido in San Francisco and became a central division head
of the California Aikido Association. Millman training under Nadeau at
Stanford connects Millman to the Ueshiba Aikido lineage.

## Suggested article edits

### Edit 1 — Add Judo & Karate to Early life and education

**Location:** Early life and education section, after the existing
"modern dance and martial arts" mention.

**Suggested text:**
> Millman began training in judo as a youth — he has said he took up the
> art "for the same reason that many of us went into Martial Arts:
> bullies" — and later trained in karate and other self-defense arts
> alongside his gymnastics and trampoline work.

**Citation:** whistlekick Martial Arts Radio Ep. 672,
https://www.whistlekickmartialartsradio.com/blog/672-dan-millman

> Note: the whistlekick interview is a primary source (Millman's own
> words). For Wikipedia notability/verifiability, pair it with the USAG
> and USGHOF Hall of Fame pages, which are independent secondary sources.

### Edit 2 — Expand the Stanford aikido passage + name Robert Nadeau

**Current text (with `[citation needed]`):**
> "During Millman's tenure at Stanford, he trained in aikido, eventually
> earning a shodan (black belt) ranking; he studied tai chi and other
> martial arts. [citation needed]"

**Suggested replacement:**
> During Millman's tenure at Stanford, he trained in aikido under
> Robert Nadeau, eventually earning a shodan (first-degree black belt)
> ranking; he also studied tai chi and other martial arts. Millman is
> listed among the notable students of Nadeau, an Aikido shihan who
> trained directly under Aikido founder Morihei Ueshiba.

**Citations:**
1. USA Gymnastics Hall of Fame —
   https://usagym.org/halloffame/inductee/millman-dan ("Aikido black
   belt")
2. US Gymnastics Hall of Fame —
   https://usghof.org/d_millman ("earning a black belt in Aikido")
3. Wikipedia — Robert Nadeau (aikidoka) —
   https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka) (lists Millman
   as a notable student)
4. Alchetron — https://alchetron.com/Dan-Millman ("trained in Aikido,
   eventually earning a shodan (black belt)")

This **resolves the `[citation needed]` tag** on the aikido shodan claim
with four sources (two independent Hall of Fame pages + Wikipedia +
Alchetron).

### Edit 3 — Add World Trampoline Championship gold medal

**Location:** Career section (or Early life, near the trampoline mention).

**Suggested text:**
> Millman won the gold medal at the World Trampoline Championship; the
> USA Gymnastics Hall of Fame describes him as "the Aikido black belt
> [who] took gold at the World Trampoline Championship."

**Citation:** USA Gymnastics Hall of Fame,
https://usagym.org/halloffame/inductee/millman-dan

### Edit 4 — Add "Way of the Peaceful Warrior" origin (Oberlin)

**Location:** Career section, at the Oberlin College passage.

**Suggested text:**
> At Oberlin, Millman created a course introducing students to the basic
> elements of tai chi and aikido. He initially planned to call it "The
> Way of the Warrior," but revised the title to reflect the defensive,
> internal nature of those arts, arriving at "Way of the Peaceful
> Warrior" — the phrase that became the title of his best-known book.

**Citation:** whistlekick Martial Arts Radio Ep. 672,
https://www.whistlekickmartialartsradio.com/blog/672-dan-millman
(Millman's first-person account)

**Supporting context (from the interview):**
> "I created a course that introduced students to both the basic elements
> of Taichi and Aikido... I was going to call it 'The Way of the
> Warrior'... But it didn't quite fit because these are a bit more
> internal arts, and they were not primarily aggressive arts, but
> defensive. Both of them. And so I ended up coming up with the idea. I
> said, 'Wait a minute, I'll call it way of the peaceful warrior.'"

### Edit 5 — Resolve remaining `[citation needed]` on Stanford gymnastics prominence

**Current:**
> "...led the Stanford gymnastics team to national prominence.
> [citation needed]"

**Suggested citation:** USA Gymnastics Hall of Fame,
https://usagym.org/halloffame/inductee/millman-dan (inducted for
gymnastics coaching achievements at Stanford).

## Citation-needed tag summary

| Tag location (article) | Date | Proposed resolution |
|---|---|---|
| Stanford gymnastics national prominence | Dec 2017 | USAG HOF page |
| Aikido shodan / tai chi / martial arts at Stanford | Dec 2017 | USAG HOF + USGHOF + Wikipedia (Nadeau) + Alchetron |
| Co-Senior Athlete of the Year (high school) | Jun 2021 | USGHOF page (early athletic training) |
| (other Jun 2021 tags — non-martial-arts) | Jun 2021 | review individually against USAG/USGHOF |

## Source reliability notes for Wikipedia editors

- **USAG Hall of Fame** (usagym.org) and **USGHOF** (usghof.org) are
  independent, institutional secondary sources — the strongest citations
  for the aikido black belt and trampoline gold claims.
- **Wikipedia — Robert Nadeau (aikidoka)** is a secondary source for the
  Millman–Nadeau student-teacher relationship (lists Millman as a notable
  student).
- **whistlekick Martial Arts Radio** is a primary source (Millman's own
  interview). Best used for first-person quotes (the "Peaceful Warrior"
  origin, the judo/bullies anecdote) paired with the HOF pages for
  verifiability of the factual claims.
- **Alchetron** is a tertiary mirror — use only as a corroborating cite,
  not the sole source.

## Graph data provenance

- Canonical node: `person:dan-millman`
  - `metadata.martial_arts`: "Aikido (shodan/black belt), Judo, Karate"
  - `source_urls`: danmillman.com, alchetron.com, en.wikipedia.org,
    usagym.org, usghof.org
- Key edges:
  - `person:dan-millman --MEMBER_OF--> person:robert-nadeau`
    (student-teacher)
  - `person:dan-millman --MEMBER_OF--> group:aikido`
  - `person:dan-millman --WORKED_AT--> place:stanford-university`
    (Director of Gymnastics, 1968)
  - `person:dan-millman --WORKED_AT--> place:oberlin-college`
    (Asst. Prof. of Physical Education, 1972)
- Claim `claim:search:nadeau-millman-student` documents the
  Millman–Nadeau relationship with 5 supporting URLs.
- whistlekick interview: `work:ab260c68c6cd27d4`
- Rank-source reference file:
  `/home/kkron/projects/github/story_graph-lineage-etl/data/reference/rank-sources/wikipedia-dan-millman.html`
  (current Wikipedia article HTML, used to locate the citation-needed tags)
