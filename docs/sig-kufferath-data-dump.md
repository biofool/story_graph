# Sig Kufferath — Complete Graph Data Dump

> Verified against the live Story Graph SQLite DB (`data/graph.db`) on
> 2026-09-08. All node IDs, edges, source URLs, and claims below were
> confirmed present in the graph. Data-quality issues are listed at the end.

## Summary

Complete dump of all Sig Kufferath data currently in the Story Graph: canonical Person node, alias/duplicate Person nodes, kkron personal-communication claims, key relationship edges, and all ingested web sources with URLs.

Canonical node ID: `person:sig-kufferath`

---

## Person Nodes

**Canonical:** `person:sig-kufferath` — "Sig Kufferath"
- `metadata.asserted_by`: kkron
- `source_urls`:
  - https://danzan.com/HTML/PEOPLE/kufferath.html
  - https://kodenkan.com/kufferath
  - https://www.kuialuaopuna.com/mi/news/sig-kufferath
  - https://www.usadojo.com/sig-kufferath
  - `kkron://personal-communication/kufferath-nadeau-bunch`

**Alias / duplicate Person nodes (spaCy-extracted variants, not yet merged):**
| Node ID | Label | Source URL |
|---|---|---|
| `person:siegfried-kufferath` | Siegfried Kufferath | https://danzan.com/HTML/PEOPLE/kufferath.html, https://www.kuialuaopuna.com/mi/news/sig-kufferath, https://www.kuialuaopuna.com/to/news/sig-kufferath |
| `person:prof-kufferath` | Prof Kufferath | https://danzan.com/HTML/PEOPLE/kufferath.html, https://www.kuialuaopuna.com/mi/news/sig-kufferath, https://www.kuialuaopuna.com/to/news/sig-kufferath |
| `person:instructor-kufferath` | Instructor Kufferath | https://danzan.com/HTML/PEOPLE/kufferath.html |
| `person:kufferath-sig-kufferath` | Kufferath Sig Kufferath | https://danzan.com/HTML/PEOPLE/kufferath.html |
| `person:kufferath-danzan` | Kufferath Danzan | https://www.usadojo.com/sig-kufferath |
| `person:kufferath-left` | Kufferath Left | https://kodenkan.com/kufferath |
| `person:shin-hori-kufferath` | Shin Hori Kufferath | https://www.usadojo.com/sig-kufferath |
| `person:sig-kufferat` (typo, no h) | — | https://www.usadojo.com/sig-kufferath |

> **Data-quality note:** These 8 variants should be merged into `person:sig-kufferath` via `ALIAS_OF` edges (or deduplicated). `person:shin-hori-kufferath` is actually his **mother** (Shin Hori Kufferath), not an alias of Sig — mis-extracted.

---

## kkron Personal-Communication Claims

All sourced from `kkron://personal-communication/kufferath-nadeau-bunch`. Confidence 0.9.

1. **Birth & lineage** (`claim:571407174e34d051`, secondary_report)
   > Sig Kufferath was born on February 16, 1911 in Honolulu, Hawaii, one of eleven children, of German/Japanese descent. His father served as a German consulate official to Japan and his mother was Japanese. As many as eleven languages were spoken in the household.

2. **Began Danzan-ryu under Okazaki** (`claim:4a5cf3f67a545d7c`, secondary_report)
   > Kufferath began studying Danzan-ryu Jujitsu under Seishiro Henry Okazaki in 1937 at the Kodenkan dojo in Honolulu. Because Kufferath was fluent in Japanese, Okazaki taught him the complete system in Japanese. He trained six days a week and earned his black belt in May 1941.

3. **Succeeded Okazaki as head of AJI** (`claim:0a48f3c6a3dbbdad`, secondary_report)
   > Following Okazaki's death in 1951, Kufferath was promoted to Shichidan (7th degree black belt) and named Professor by the American Jujitsu Institute. He was elected to succeed Okazaki as head of the AJI.

4. **Relocated to California, opened Nikko Kodenkan** (`claim:062dc00c871d8e21`, secondary_report)
   > Kufferath relocated to California in 1960 and opened the Nikko Kodenkan dojo in Mountain View. He cross-trained in Judo (Nidan, 1956) and Aikido (Nidan, 1965).

5. **Shared Castro Street dojo with Nadeau** (`claim:41ffb3c0123fe287`, first_person)
   > Robert Nadeau and Sig Kufferath shared dojo space at 194-198 Castro Street, Mountain View (the Jurian Building) starting around 1966, when Nadeau returned from Japan after training under Morihei Ueshiba.

6. **Cross-pollination with Nadeau** (`claim:395e3214a8d11e41`, first_person)
   > Because they operated out of the same facility on Castro Street, Kufferath and Nadeau met frequently and cross-pollinated their respective martial arts knowledge, allowing Aikido and Danzan Ryu Jujitsu students to interact closely.

7. **Seifukujutsu mastery** (`claim:cd84f308609cf5ed`, secondary_report)
   > Kufferath graduated from Okazaki's Nikko Restoration Sanatorium, mastering Seifukujutsu (Japanese physical therapy, adjustment, and restorative arts). He maintained an active practice and taught these healing arts alongside jujitsu until shortly before his death in 1999.

8. **Joined AJJF, co-founded KDRJA & Kilohana** (`claim:488f57275770869c`, secondary_report)
   > Kufferath joined the American Judo & Jujitsu Federation (AJJF) in 1983, which awarded him the title of Shihan in 1988. He co-founded the Kodenkan Danzan Ryu Jujitsu Association and the Kilohana Martial Arts Association.

9. **Richard Bunch as operational link** (`claim:a74d408f8be630b5`, first_person)
   > Richard Bunch was the operational link between Robert Nadeau's Aikido and Sig Kufferath's Danzan Ryu Jujitsu communities in Northern California.

10. **Bunch trained under Kufferath** (`claim:e6cf80a1a963cbe3`, secondary_report)
    > Richard Bunch began training under Professor Kufferath as a teenager and became Kufferath's Associate and Chief Instructor at the Nikko Ju Jitsu School in San Jose, California.

11. **Nadeau transitioned to sharing space with Bunch** (`claim:d49902e59d6dfa1f`, first_person)
    > When Nadeau expanded his schools, he transitioned from sharing space with Kufferath directly to sharing space with Richard Bunch.

12. **CAA formation** (`claim:ba4482a93b79a7cd`, first_person)
    > Through the tight-knit working relationship with Richard Bunch, Nadeau maintained ongoing contact with several major Ju-Jitsu schools, which directly led to the landmark formation of the California Aikido Association (CAA), where Nadeau became a central division head.

---

## Key Relationship Edges (sig-kufferath)

| Source | Relation | Target | Evidence |
|---|---|---|---|
| `person:sig-kufferath` | FOUNDED | `group:aji` | https://www.usadojo.com/sig-kufferath |
| `person:sig-kufferath` | FOUNDED | `group:american-jujitsu-institute` | https://www.usadojo.com/sig-kufferath |
| `person:sig-kufferath` | FOUNDED | `group:okazaki` | https://www.usadojo.com/sig-kufferath |
| `person:sig-kufferath` | MEMBER_OF | `group:american-jujitsu-institute` | kkron://personal-communication/kufferath-nadeau-bunch |
| `person:sig-kufferath` | MEMBER_OF | `group:kodenkan` | kkron://personal-communication/kufferath-nadeau-bunch |
| `person:sig-kufferath` | WORKED_AT | `place:castro-st-mountain-view-jurian-building` | kkron://personal-communication/kufferath-nadeau-bunch |
| `person:robert-nadeau` | WORKED_AT | `place:castro-st-mountain-view-jurian-building` | kkron://personal-communication/kufferath-nadeau-bunch |
| `person:richard-bunch` | MEMBER_OF | `group:nikko-jujitsu-school` | kkron://personal-communication/kufferath-nadeau-bunch |
| `person:robert-nadeau` | MEMBER_OF | `group:california-aikido-association` | kkron://personal-communication/kufferath-nadeau-bunch |

> **Data-quality note:** The `FOUNDED --> group:okazaki` edge is semantically wrong — Kufferath did not "found" Okazaki (Okazaki is a person, Henry Seishiro Okazaki, his teacher). This edge should be removed or re-typed (e.g. `MENTIONS` or a student-of relationship). The `FOUNDED --> group:aji` and `FOUNDED --> group:american-jujitsu-institute` edges are also questionable — Kufferath *succeeded* Okazaki as head of AJI, he did not found it.

---

## Ingested Web Sources (with URLs)

| # | Title | Platform | URL |
|---|---|---|---|
| 1 | Prof. Sig Kufferath | danzan.com | https://danzan.com/HTML/PEOPLE/kufferath.html |
| 2 | Kufferath - Kodenkan Jujitsu & Restoration Therapy | kodenkan.com | https://kodenkan.com/kufferath |
| 3 | Sig Kufferath Danzan Ryu Jujitsu | usadojo.com | https://www.usadojo.com/sig-kufferath |
| 4 | Sig kufferath \| Ku'ialuaopuna (mi) | kuialuaopuna.com | https://www.kuialuaopuna.com/mi/news/sig-kufferath |
| 5 | Sig kufferath \| Ku'ialuaopuna (to) | kuialuaopuna.com | https://www.kuialuaopuna.com/to/news/sig-kufferath |
| 6 | Kufferath-Nadeau-Bunch connection research (kkron) | kkron (personal communication) | `kkron://personal-communication/kufferath-nadeau-bunch` |
| 7 | Wikipedia article draft: Siegfried Kufferath (kkron) | kkron (personal communication) | `kkron://wikipedia-draft/sig-kufferath` |

### Source 1 — danzan.com (Prof. Sig Kufferath)
Biographical page maintained by George Arrington. Covers: birth 1911 Honolulu, German/Japanese descent, 11 languages at home, University of Hawaii track star, began jujitsu with Okazaki 1937, black belt 1941, Mokuroku (teacher's scroll), teaching partners Bing-Fai Lau and Esther Azumi, Kodenkan and Kaheka Lane dojos, learned system in Japanese, Seifukujutsu, 1948 Special Black Belt Class → Kaidensho + Shihan title, elected to succeed Okazaki as Professor 1952, continued until 1960 move to mainland, 1993 Kodenkan Jujitsu Okugi, held black belts in Judo and Aikido, died May 7 1999 Santa Clara CA. Includes photo captions (instructor scroll 1942, Hane Goshi on Bing-Fai Lau 1942, Tech Sergeant US Army ~1946, Kaheka Lane Dojo, children's class, Joe Holck, James Mitose visit, Tony Janovich instructor scroll, Ohio class 1980s, 1990 Ohana, 1992 Ohana gathering of professors).

### Source 2 — kodenkan.com
Prof. Sig Kufferath, 10th Dan. Began study under Okazaki 1937, black belt 1941, instructor 1942. Studied Chinese stick arts, Kiai, Karate Jitsu, Nerve arts, Shingen No Maki, Shinyo No Maki, Naihan No Shodan, Kumite. Graduated Nikko Restoration Sanatorium Seifuku Jitsu 1943. Chief instructor of Kodenkan late 1940s. Elected by AJI board to succeed Okazaki, official Oct 6 1953. Left Hawaii 1957 for California (Willow Glen, San Jose), taught at Bill Montero's dojo, moved to Santa Clara, 1960 Los Altos Parks & Recreation, 1964 Ed Dressen school. 1973 began teaching with Tony Janovich at Kodenkan Jujitsu School (El Camino, Santa Clara). 18 years of Restoration Therapy certification courses. Kodenkan Jujitsu Okugi™. Died May 7 1999 Santa Clara, memorial May 15 1999.

### Source 3 — usadojo.com (USAdojo, May 7 1999)
Born Feb 16 1911 Honolulu, second youngest of 11 children, father C. Th. Kufferath (German Consulate Tokyo 26 years, 7 siblings born in Kobe, one brother Tasmania, one sister Berlin, Sig and younger brother Arnold born Honolulu). McKinley High School quarter-miler, 3-time Hawaiian A.A.U. 440-yard champion late 1920s/early 30s. Worked as auditor for City and County of Honolulu. Began jujitsu under Okazaki 1937, black belt 1941, instructor 1942, organized Nikko club at Kaheka Lane Judo School. Graduated Nikko Restoration Sanatorium Seifuku Jitsu 1943. Accompanied Okazaki on house calls. (Full text truncated in graph — 7809 chars omitted.)

### Source 4 & 5 — kuialuaopuna.com (mi and to mirrors)
Same biographical text as danzan.com source (George Arrington's page mirrored). Born Honolulu Feb 16 1911, 11 children, German/Japanese descent, track star, began with Okazaki 1937, black belt 1941, Mokuroku, Bing-Fai Lau and Esther Azumi, Kodenkan and Kaheka Lane dojos, Seifukujutsu, 1948 Special Black Belt Class → Kaidensho + Shihan, elected Professor 1952, continued to 1960, 1993 Okugi, Judo and Aikido black belts, died May 7 1999 Santa Clara.

### Source 6 — kkron personal communication
Research summary documenting the Kufferath-Nadeau-Bunch connection: shared dojo at 194-198 Castro St Mountain View (Jurian Building) ~1966, Bunch as operational link, Bunch trained under Kufferath as teenager → Chief Instructor at Nikko Ju Jitsu School San Jose, Nadeau later shared space with Bunch, alliance led to California Aikido Association formation.

### Source 7 — kkron Wikipedia draft
Draft Wikipedia article for Siegfried "Sig" Kufferath (Feb 16 1911 – 1999), German-Japanese martial artist and physical therapist, grandmaster (Shihan) of Danzan-ryu Jujitsu, head of American Jujitsu Institute. Covers birth, Okazaki training 1937, black belt May 1941, own school 1942, instructed Honolulu Police and US military during WWII, succeeded Okazaki 1951, California 1960, Nikko Kodenkan Mountain View, Judo Nidan + Aikido Nidan, AJJF 1983, Shihan 1988, co-founded Kodenkan Danzan Ryu Jujitsu Association and Kilohana Martial Arts Association, Seifukujutsu from Nikko Restoration Sanatorium.

---

## Known Inaccessible Sources (NOT ingested — returned HTTP 403)

These URLs were attempted but blocked by server-side WAF/nginx and are **not** in the graph:
- https://www.ajjf.org/about-the-ajjf/in-memoriam/professor-sig-kufferath/
- https://www.ajjf.org/professor-sig-kufferath-in-memoriam
- https://jujitsuamerica.org/professor-richard-bunch-certified-ja-instructor/

---

## Data-quality issues to address

1. **8 duplicate Person nodes** for Sig Kufferath should be merged via `ALIAS_OF` into `person:sig-kufferath`.
2. **`person:shin-hori-kufferath` is his mother**, not an alias — should be reclassified as a separate Person with a `MENTIONS`/family relationship.
3. **`FOUNDED --> group:okazaki` edge is wrong** — Okazaki is his teacher, not something he founded. Should be removed or re-typed.
4. **`FOUNDED --> group:aji` / `group:american-jujitsu-institute`** — Kufferath succeeded Okazaki as head of AJI, he did not found it. Should be `MEMBER_OF` / `LED` (not `FOUNDED`).
5. **`person:sig-kufferat`** (typo, missing final h) is a duplicate from usadojo.com extraction.
6. **AJJF and Jujitsu America pages remain blocked** — content about Kufferath's AJJF involvement (1983 join, 1988 Shihan) is currently only sourced via kkron personal communication, not independently verifiable from those orgs' own sites.

---

## Graph provenance

- Data extracted from `graph_snapshot/` JSONL files (nodes, edges, sources, claim_sources).
- Total Kufferath-mentioning nodes: 231, edges: 373 (most are `MENTIONS` edges from ingested Works).
- kkron assertions are first-class evidence per `AGENTS.md` — recorded as `source_class: primary_first_person`.

Generated with [Devin](https://devin.ai)

