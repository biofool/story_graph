# Journalistic & Archival Sources — Two Threads

**Date**: 2026-08-24
**Brief**: Find journalistic sources for (1) the founding of The Source restaurant
and the claim that Richard Moon introduced Jim Baker to Yogi Bhajan, and (2) the
Cyprus Conflict Resolution Trainers Group / Cyprus Fulbright Commission / Doug
Stone / Richard Moon thread.
**Method**: Independent web search and document retrieval, mirroring the queries
`scripts/03_targeted_entity_research.py` issues via Gemini + Google Search
grounding. No paid Gemini/Vertex calls were made — same precedent as the
2026-08-23 validation run (`docs/targeted_research_validation_2026-08-23.md`).

**Note on the Cyprus leads and `allowed_domains`**: the README's allowed-domain
list gates only `scripts/01`'s broad BFS crawl. `scripts/03` builds a fresh
`WebCrawler` per discovered URL with `allowed_domains={get_domain(url)}`, so the
Cyprus-thread domains (cyprusreview.org, escholarship.org, imtd.org, …) need no
config change to be fetchable when Phase 2 next runs.

---

## Headline findings

1. **A citation in this repo was false and has been withdrawn.** Three Claim
   nodes asserted that pleasekillme.com's Father Yod profile reported "a March
   1971 meeting of Richard Moon, Father Yod, and Yogi Bhajan." That article says
   no such thing. It never mentions any Moon. Its March 1971 passage is about
   Jim Baker resolving to become a spiritual leader after a 90-day India trip
   with Yogi Bhajan and 83 other 3HO students. Details and remediation below.

2. **No journalistic source names who introduced Jim Baker to Yogi Bhajan.**
   That Baker was Bhajan's student is very well established, including in
   peer-reviewed work. *Who made the introduction* is undocumented in every
   source found. kkron's account is currently the only evidence for Richard
   Moon's role, and it is now filed as such.

3. **The "Doug Stone was employed by the Cyprus Fulbright Commission"
   hypothesis is not supported, and is mildly contradicted.** The contemporaneous
   insider account (Broome 1998) names the Cyprus Consortium's team leaders and
   every Fulbright Scholar in Conflict Resolution. Stone is not among them and
   appears on no Cyprus roster found.

4. **Richard Moon's Cyprus work is documented — but only by Richard Moon.**
   His own biography places him in Cyprus and Bosnia under IMTD auspices "in
   association with the Fulbright Commission." No independent source corroborates
   it. This is autobiography, not journalism.

5. **The graph was conflating three different men named Richard Moon.** Fixed;
   see "Named-entity disambiguation" below.

---

## Thread 1 — LA, 1965–1975: The Source, Jim Baker, Yogi Bhajan, Richard Moon

### Ranked sources

#### Tier A — peer-reviewed, citation-rich, contemporaneous-sourced

**A1. Philip Deslippe, "From Maharaj to Mahan Tantric: The Construction of Yogi
Bhajan's Kundalini Yoga," *Sikh Formations* 8(3), December 2012, pp. 369–387.**
[Open-access PDF](https://escholarship.org/content/qt6r63q6qn/qt6r63q6qn_noSplash_fbbba186685c0619c35208f88b1f29ec.pdf)

> "Yogi Bhajan told Jim Baker, one of his senior students in Los Angeles, to
> come on the trip for the purpose of getting the blessing of his teacher"
> (Aquarian 2007, 46).

*Why it matters*: the strongest source in either thread. Peer-reviewed, built
from "rare early texts and interviews with early students and associates," and it
cites page numbers. It establishes Baker as a *senior* Bhajan student in LA — the
single best-supported link in the whole Baker↔Bhajan question. It says nothing
about who introduced them. Its bibliography is also the richest vein of
contemporaneous journalism found (see A2–A5).
→ Stored as `claim:citation:e47fb42e5b9a39df`, confidence 0.85.

#### Tier B — contemporaneous journalism, 1968–1971 (cited by Deslippe, full text not yet retrieved)

These are the primary 1965–1975 articles the brief asked for. All are recorded
from Deslippe's bibliography; none has been read in full, because they sit behind
the LA Times historical archive / ProQuest / Newspapers.com paywalls. **Retrieving
these is the highest-value next step for this thread.**

| # | Citation | Relevance |
|---|---|---|
| **A2** | Marty Altschul, "Tense housewives, businessmen try relaxing Hindu way," **Los Angeles Times, 22 June 1969** | Earliest LA Times coverage of Yogi Bhajan teaching in LA found. Two months after The Source opened, weeks after Baker reportedly met Bhajan. Most likely single article to place named early students. |
| **A3** | William L. Claiborne, "Yoga students set India trip for drug study," **The Washington Post, 23 December 1970, B2** | Contemporaneous report on the India trip Baker went on. Deslippe cites it for Bhajan's stated purpose (getting American youth off drugs via yoga). |
| **A4** | Edna Hampton, "Yoga's challenges and promises," **The Globe and Mail, 28 November 1968** | Bhajan's pre-LA Toronto period; Deslippe cites it for his shifting account of how long he had studied. |
| **A5** | Suresh Sharma, "Warrant issued against Yogi," *Hindustan Times*, 19 March 1971; Anon., "Yogi bailed out, flies back to US," *Hindustan Times*, 20 March 1971 | The India trip's collapse, same month as the pleasekillme "March 1971" passage. |

Both A2 and A3 are stored in the graph with `source_url` pointing at **Deslippe's
PDF**, not at latimes.com or washingtonpost.com. A `source_url` is a provenance
assertion — it has to point at something that demonstrably says this. Deslippe's
bibliography does; a newspaper homepage says nothing about a 1969 article, and a
URL reconstructed from a bibliography entry may not resolve at all. The claim text
says plainly that it records what Deslippe's bibliography holds, not text read in
the Times or the Post. Re-point these once the articles themselves are retrieved.

Also in Deslippe's bibliography, lower relevance: Anon., "Yogi on yoga," *Santa Fe
New Mexican*, 20 March 1970; Brett Gray, "World must purify self soon, yoga
warns," *Orlando Sentinel*, 31 May 1970; Anon., television notice, *Arizona
Republic*, 28 November 1970.

#### Tier C — modern journalism on The Source (retrospective, no Moon)

| # | Source | Key content |
|---|---|---|
| **C1** | Doug Harvey, "Father Yod Knew Best," **LA Weekly, 29 August 2007** | Baker "opened his third restaurant — the Source" in early 1969 at Sunset and Sweetzer; became "a devotee of Sikh kundalini master Yogi Bhajan." Quotes *The Garden Island* (Hawaii) contemporaneously. No Moon. |
| **C2** | Amanda Sheppard, "Father Yod: War Hero, Bank Robber, Polygamist Cult Leader and Psychedelic Recording Artist!," **Please Kill Me, 18 September 2018** | "In March 1971, Jim Baker decided that it was his destiny to become a spiritual leader. This came to him in the wake of a disastrous 90-day trip to India with 83 of his fellow 3HO yoga students and Yogi Bhajan." Also: Baker "led Sunday meditation classes in the back of The Source, using the naam of Ek Ong Kar Sat Nam Siri Wahe Guru he learned at 3HO." **No Moon anywhere.** |
| **C3** | LA Times, "How L.A. cult the Source Family became hot content in 2023," 12 April 2023 | Already crawled (`work:a7a7e909d30a4e18`). Retrospective. |
| **C4** | *The New York Times*, "Spirit of Dashing Founder Guides Commune," 23 October 1976 | "He started the Aware Inn, which became a hangout for the hip"; "Mr. Baker founded The Source about 1969." Closest thing to contemporaneous national coverage. Full text not retrieved (paywall). |
| **C5** | Atlas Obscura, "The Cult Roots of Health Food in America"; LAist, Eater LA, Hollywood Reporter | Corroborate Aware Inn ~1957–58 at 8828 Sunset Blvd. and The Source opening 1 April 1969 at 8301 Sunset Blvd. Already in graph or in the 2026-08-23 validation. |

#### Tier D — insider / primary, not journalism

- **Isis Aquarian & Electricity Aquarian, eds., *The Source: The Untold Story of
  Father Yod, Ya Ho Wa 13 and The Source Family*** (Process Media, 2007). The
  insider roster and the source Deslippe cites at p. 46. **Not yet consulted
  directly** — the most likely place a Source Family member named Moon would
  appear, and the obvious next acquisition.
- **fatheryod.org timeline** (Source Foundation, run by former members): "In May
  1969 Jim Baker met Yogi Bhajan – his first true 'Spiritual Father'." Dates the
  meeting but not its broker. Self-published by the movement.
- **lifeinthesourcefamily.blogspot.com**, "The Wacko World of Yogi Bhajan," Laura
  Garon, 7 November 2015. Ex-member memoir. Confirms Baker treated Bhajan as
  "spiritual father." **No Moon, no Rochelle.**

### Explicit search for Richard Moon / Rochelle Moon

Searched across all of the above plus targeted queries. Results:

- **"Richard Moon" + The Source / Aware Inn / Father Yod / Yogi Bhajan**: no hit
  in any journalistic source, in either the 1965–75 material or the retrospectives.
- **"Rochelle Moon"**: no hit anywhere, in any context — not LA spiritual
  communities, not 3HO, not martial arts, not the Source Family.
- Source Family members took Aquarian names (Isis, Electricity, Djin, Octavius,
  Sunflower). If Moon was in the Family, he would likely appear under one, which
  is a structural reason surname searches keep returning nothing — and a reason
  the Aquarian book (D1) is the right next source.
- Richard Moon's own published biographies (quantumaikido.com, nautilus.org,
  openmindadventures.com, createabeautifulworld.org, Simon & Schuster) **do not
  mention** The Source, Jim Baker, Father Yod, Yogi Bhajan, Kundalini Yoga, or
  Los Angeles in the 1960s–70s. His public bio begins martial arts in 1969 and
  aikido under Robert Nadeau in 1971, in the San Francisco Bay Area.

**Verdict on the hypothesis "Richard Moon introduced Jim Baker to Yogi Bhajan":
no journalistic confirmation, and no indirect journalistic support either.** The
strongest indirect evidence available is only for the *surrounding* facts: Baker
was demonstrably one of Bhajan's senior LA students (A1), and Baker was
demonstrably running The Source when that relationship formed (C1, C2). Nothing
found bears on the introduction itself. This remains a hypothesis grounded in
kkron's oral account, and is now stored that way.

### The withdrawn pleasekillme citation

The repo previously carried three Claim nodes and one Event node asserting that
pleasekillme.com reported a March 1971 meeting of Moon, Baker and Bhajan:

- `claim:citation:1f97a7769d7863cd`, `claim:citation:46daaf7e52bb06ea`,
  `claim:citation:f4e5ff0dabb9c656`
- `event:march-1971-meeting-of-richard-moon-father-yod-and-yogi-bhajan`
- plus a false `work:eb9ed8858a7734a5 MENTIONS person:richard-moon` edge

Re-reading Sheppard's article shows the underlying claim was misattributed: the
article's March 1971 content is C2 above, and Moon is absent from it. This is the
same defect class as commit `03f2735` (ordering assertions injected into claim
text kkron never made).

**Remediation** (all applied):

- The three claims, the Event, their edges and claim-source links are removed
  from `graph_snapshot/`, and the three leads are removed from `DEFAULT_LEADS`.
- The `MENTIONS` edges from the pleasekillme Work node to Baker and Yogi Bhajan
  are **kept** — the article genuinely mentions both. Only the Moon edge is gone.
- The introduction hypothesis is re-filed on the kkron path
  (`claim:kkron:8595b54efb638272`, capped at 0.5,
  `pending_independent_corroboration=True`) where an uncorroborated first-hand
  account belongs. It is attached to the Event node the crawl had already
  produced — `event:meeting-of-baker-and-yogi-bhajan`, dated May 1969 — rather
  than to a new "Introduction of…" node. `event_id()` slugifies the label, so a
  near-synonym would have forked one real meeting into two nodes and left the
  contradiction detector unable to relate kkron's account to the crawled facts
  about the same event.
- Two accurate citation leads replace it: the Deslippe claim (A1) and the actual
  Sheppard India-trip claim (C2), each quoting what its source really says.

---

## Thread 2 — Cyprus: CRTG, Fulbright Commission, Doug Stone, Richard Moon

### Ranked sources

#### Tier A — contemporaneous insider account, citation-rich

**A1. Benjamin J. Broome, "Overview of Conflict Resolution Activities in Cyprus:
Their Contribution to the Peace Process," *The Cyprus Review* 10(1), 1998,
pp. 47–66.**
[PDF](https://cyprusreview.org/index.php/cr/article/download/490/438)

> "a number of conflict resolution workshops were held in the summer of 1994
> organized by the Cyprus Fulbright Commission (CFC) and conducted by the Cyprus
> Consortium, a group that consists of IMTD, the Conflict Management Group (CMG)
> of Harvard University, and National Training Laboratory (NTL) based in
> Virginia. The team leaders for this effort were Louise Diamond and her
> colleague Diana Chigas (from CMG). Funded by U.S. Agency for International
> Development and administered by CFC…"

> "Before taking up the Fulbright position in September of 1994, I participated
> as a member of the Cyprus Consortium's training team for the summer 1994
> workshops… They called themselves the 'Conflict Resolution Trainers'."

> "I came as the initial Fulbright Scholar in Conflict Resolution and repeated
> the next 2 terms… Philip Snyder took up the position of Fulbright Scholar in
> conflict resolution during 1997, and John Ungerleider and Marco Turk came in
> fall 1997."

*Why it matters*: written by the man who held the Fulbright post, two to four
years after the events, in a peer-reviewed regional journal. It answers the
brief's core structural question — the funding and contracting chain is
**USAID → Cyprus Fulbright Commission (administers) → Cyprus Consortium
(IMTD + CMG + NTL, conducts) → CRTG (the trained Cypriots)** — and it names
individuals at each level. **The word "Stone" does not appear anywhere in the
paper.**
→ Stored as `claim:citation:583b893760f88efa`, confidence 0.9.

#### Tier B — corroborating rosters

| # | Source | Bearing on the hypothesis |
|---|---|---|
| **B1** | Wikipedia, "Cyprus Conflict Resolution Trainers Group" (13 cited academic references incl. Broome 1997/1998, Diamond & Fisher 1995, Wolleh 2001) | Names Kelman, Fisher, Diamond, Chigas, Hadjittofis, Broome + ~30 Cypriot members. **No Doug/Douglas Stone. No Richard Moon.** |
| **B2** | Future Worlds Center wiki, CRTG page | 30 members listed. **No Stone, no Moon.** |
| **B3** | Oliver Wolleh, *Local Peace Constituencies in Cyprus: The Bi-Communal Trainers Group* (Berghof Report 8, 2001) | The other citation-rich monograph. **Not retrieved** — the CDA Collaborative mirror is behind a captcha. Worth a retry via Berghof directly. |
| **B4** | Keith E. Peterson, *American Dreams: The Story of the Cyprus Fulbright Commission* (Armida Books, 2024); Cyprus Fulbright History Project | Institutional history: the Commission "poured millions of dollars into the quest for peace" and ran 200+ conflict-resolution programs. The natural place to settle any "employed by the Commission" question definitively. **Not yet consulted.** |

#### Tier C — self-published biography (not journalism)

| # | Source | Content |
|---|---|---|
| **C1** | Doug Stone bio — Triad Consulting Group / stoneandheen.com / Harvard Law School | Lecturer on Law at HLS; Harvard Negotiation Project 1988/1989–1998/1999 with Roger Fisher, Bruce Patton, Sheila Heen; has worked with "Greek and Turkish political and community leaders in Cyprus." **Names no sponsor, no employer, no date, and no organization for the Cyprus work.** Never mentions the Fulbright Commission, CMG, the Cyprus Consortium, or the CRTG. |
| **C2** | Richard Moon bio — openmindadventures.com | "He has been involved in international peace-building, having worked in Cyprus and Bosnia under the auspices of the Institute for Multi-Track Diplomacy, in association with the Fulbright Commission, the American Embassy in Cyprus, Conflict Management Group and the Harvard Negotiation Project." |
| **C3** | Richard Moon bio — nautilus.org (Nautilus Institute senior associate) | "He has engaged in international peace building in Cypress [sic] and Bosnia." Does not name IMTD, Fulbright or Harvard. |
| **C4** | Secondary summaries of Moon's book jacket / IMTD material | "In the mid-1990s, he was teaching conflict resolution at Harvard Law School and was part of the staff working on a weeklong mediation project in Cyprus"; separately, "Richard Moon joined IMTD at the first Lake Trails camp in **1999**" to teach aikido as a conflict-resolution tool. |

### Testing the two hypotheses

**H1: "Doug Stone was employed by / formally contracted by / regularly engaged by
the Cyprus Fulbright Commission to train the CRTG."**

*Not supported. Mildly contradicted.* Applying the brief's own
formal-vs-informal distinction:

- **Formal appointment by the Commission** has a specific, documented form: the
  *Fulbright Scholar in Conflict Resolution* residency, requested locally and
  brought about by Executive Director Daniel Hadjittofis. Its four holders are
  named in A1: **Broome (1994–97), Philip Snyder (1997), John Ungerleider and
  Marco Turk (from fall 1997)**. Stone is not one of them.
- **Contracted delivery** ran through the Cyprus Consortium (IMTD + CMG + NTL),
  under USAID funding administered by the Commission. Stone appears on no
  Consortium roster found, and was at the Harvard **Negotiation Project** — a
  distinct organization from **Conflict Management Group**, though both Harvard-
  adjacent and sharing Roger Fisher's lineage, which is a plausible source of the
  confusion.
- **Informal participation in a training team** remains entirely possible and is
  the reading his own bio supports: he "worked with Greek and Turkish political
  and community leaders in Cyprus." That is a real claim about activity. It is
  not a claim about employment, and he does not make one.

→ Stored as `claim:kkron:f27d36ff1e898050` at confidence **0.2** — the lowest of
any kkron lead, reflecting active non-support rather than mere absence of evidence.

**H2: "Richard Moon's conflict-resolution work connects to Doug Stone's."**

*Plausible but undocumented.* The overlap is real and specific — both were at
Harvard Law School teaching negotiation/conflict resolution in the mid-1990s, and
both did Cyprus work — but **no source, journalistic or otherwise, places them in
the same room, project, or team.** No source found mentions both men. Moon's
Cyprus involvement is attested only by Moon; the one dated IMTD reference puts
him at a Lake Trails camp in **1999**, after the 1994–97 CRTG core period.

Nothing found connects Moon's Cyprus work to his earlier Los Angeles years, in
either direction.

---

## Named-entity disambiguation (and a bug it exposed)

The brief flagged disambiguation as critical. It was right: `person:richard-moon`
in this graph was a **merged biography of three unrelated men**, all reachable
from one node.

| Person | Evidence in graph | Now |
|---|---|---|
| **Richard Moon, aikido teacher** — 6th dan, Aikido of Marin / City Aikido SF, *Quantum Aikido*, IMTD Cyprus & Bosnia; kkron's subject | kkron's 3 first-hand claims | `person:richard-moon-aikido` |
| **Richard Moon, Canadian constitutional-law professor** — Univ. of Windsor, Oxford, Queen's, Trent, Centre for Free Expression, UCL | 1 claim + 4 faculty-page Works | `person:richard-moon-law-professor` |
| **Richard Moon, Australian chef** — Blue Mountains, Red Door Café, *Moon on a Spoon*, husband of Michael Burge | 17 claims from burgewords.com + 4 Events | `person:richard-moon-chef` |

Before the fix the graph asserted, as one person, a law professor who cooked in
Katoomba and worked at Father Yod's Source restaurant.

**Fix**: `HOMONYM_DISAMBIGUATION` in `src/extractor/alias_resolver.py` resolves
same-name/different-person collisions by **publishing domain** — the only signal
available at extraction time. `canonical_person()`, `person_id()` and
`resolve_target_id()` take an optional `source_url`, threaded through
`process_page` and both extractors. Names in the table have **no unqualified
canonical form**: an unknown domain still resolves to a named person, so the
graph can never re-assert a bare merged "Richard Moon." Doug Stone is registered
pre-emptively for the same reason. Covered by `TestHomonymDisambiguation` in
`tests/unit/test_alias_resolver.py`.

---

## Evidence summary

| Relationship | Best evidence | Type | Strength |
|---|---|---|---|
| Jim Baker → founded The Source (1969) | Wikipedia, NYT 1976, LAist, Eater LA, LA Weekly, Hollywood Reporter | Journalistic, multi-source | **Strong** |
| Jim Baker → founded Aware Inn (1957/58) | Restaurant-ing Through History, LAist, NYT 1976, Hollywood Reporter | Journalistic, multi-source | **Strong** |
| Jim Baker → senior student of Yogi Bhajan | Deslippe 2012 (A1), citing Aquarian 2007 p. 46 | Peer-reviewed academic | **Strong** |
| Yogi Bhajan → taught Kundalini Yoga in LA 1968–71 | Deslippe 2012 + LA Times 1969 (A2), Globe & Mail 1968 (A4) | Academic + contemporaneous press | **Strong** (press unread) |
| Baker & Bhajan → 1970–71 India trip | Sheppard 2018 (C2), Claiborne, *Washington Post* 1970 (A3) | Journalistic | **Moderate–strong** |
| **Richard Moon → introduced Baker to Bhajan** | kkron only | Oral account | **Hypothesis** |
| **Richard Moon → worked at The Source / Aware Inn** | kkron only | Oral account | **Hypothesis** |
| Richard Moon → Wild Mountain Cafe | kkron, low confidence | Oral account | **Weak hypothesis** |
| USAID → funded Cyprus CR training | Broome 1998 (A1) | Peer-reviewed insider | **Strong** |
| Cyprus Fulbright Commission → administered / organized | Broome 1998 (A1), Wikipedia (B1) | Peer-reviewed insider | **Strong** |
| Cyprus Consortium = IMTD + CMG + NTL | Broome 1998 (A1) | Peer-reviewed insider | **Strong** |
| Cyprus Consortium → trained CRTG | Broome 1998 (A1) | Peer-reviewed insider | **Strong** |
| Richard Moon → IMTD Cyprus/Bosnia work | Moon's own bio (C2) | Self-published | **Weak** |
| **Doug Stone → employed by Cyprus Fulbright Commission** | none; absent from every roster | — | **Not supported** |
| **Doug Stone ↔ Richard Moon** | none; no source names both | — | **No evidence** |

---

## Next steps, in order of expected yield

1. **Isis Aquarian (ed.), *The Source*** (Process Media, 2007) — the insider
   roster, and Deslippe's own source at p. 46. Search it for Moon, and for
   Aquarian names matching a Richard Moon. Highest yield for Thread 1.
2. **LA Times 22 June 1969 (A2)** via ProQuest Historical Newspapers or the LA
   Times archive. The single most likely contemporaneous article to name early
   Bhajan students in LA.
3. **Ask Richard Moon directly.** He is alive, publishing (*Quantum Aikido*,
   Inner Traditions/Simon & Schuster, with 2026 podcast appearances), and the
   only living witness to both threads. A recorded first-person account would
   outrank everything currently supporting either hypothesis.
4. **Peterson, *American Dreams: The Story of the Cyprus Fulbright Commission***
   (2024) and the Cyprus Fulbright History Project — settles H1 definitively.
5. **Wolleh, Berghof Report 8 (2001)** via Berghof directly (CDA mirror is
   captcha-blocked).
6. *The New York Times*, 23 October 1976 full text — closest contemporaneous
   national coverage of Baker.
