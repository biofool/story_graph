"""
Pure(ish) helpers for scripts/03_targeted_entity_research.py.

Kept in a separate, dash-free module — mirroring scripts/_pipeline_helpers.py
— because a script filename that starts with a digit (03_...) can't be
imported with a normal `import` statement. Tests and the CLI script both
import from here instead.

Two kinds of helpers live in this module:

- Pure functions/data with no I/O at all (``ResearchLead``, ``DEFAULT_LEADS``,
  ``build_search_queries``, ``effective_kkron_confidence``,
  ``build_kkron_claim_record``, ``filter_new_urls``) — covered by
  tests/unit/test_targeted_research_helpers.py.
- DB-writing (but not network-calling) helpers (``ensure_kkron_source``,
  ``store_kkron_claim``) that store kkron's own first-hand claims using the
  same GraphDB/GraphNode/GraphEdge storage layer as scripts/_pipeline_helpers
  — covered by tests/integration/test_targeted_research_pipeline.py.

None of this module writes to or reads from ``graph_snapshot/`` directly —
that JSON-snapshot-is-source-of-truth load/export lifecycle lives in
scripts/03_targeted_entity_research.py's ``main()``, via
src/storage/json_export.py. This module only ever touches the ``GraphDB``
instance it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.extractor.alias_resolver import (
    HOMONYM_DISAMBIGUATION,
    canonical_group,
    canonical_person,
    canonical_place,
    event_id,
    group_id,
    person_id,
    place_id,
    work_id,
)
from src.storage.graph_db import GraphDB
from src.storage.models import (
    BiasHint,
    ClaimStance,
    ClaimType,
    ClaimSourceLink,
    EvidenceMode,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)
from src.utils.text_utils import get_domain, stable_hash

# ---------------------------------------------------------------------------
# The "asserter" identity used for every claim that originates from kkron's
# own first-hand account rather than an independently crawled/searched web
# source. Deliberately kept out of the alias_resolver historical-person
# registry: this is a *source* node (like a quoted speaker), not a Source
# Family historical figure.
# ---------------------------------------------------------------------------
KKRON_SOURCE_PERSON_ID = "person:kkron-project-owner"
KKRON_SOURCE_LABEL = "kkron (project owner, first-hand account)"

KKRON_WORK_ID = "work:kkron-personal-communication"
KKRON_SOURCE_URL = "kkron://personal-communication"

# Ceiling applied to every kkron first-hand claim's *stored* confidence, no
# matter how sure kkron says he is (see ResearchLead.kkron_confidence). This
# guarantees a first-hand, not-yet-independently-corroborated account can
# never outrank a claim that *was* corroborated by an independently found
# web source (GeminiExtractor claims can score up to 1.0). As scripts/03
# finds independent corroborating sources for the same relation, those
# claims are stored separately at their own (uncapped) confidence — the
# kkron claim itself is not silently upgraded, so the graph always shows
# both "what kkron said" and "what was independently found".
KKRON_CONFIDENCE_CEILING = 0.5

_ENTITY_ID_FN = {
    "person": person_id,
    "group": group_id,
    "place": place_id,
    "event": event_id,
}

_CANONICAL_FN = {
    "person": canonical_person,
    "group": canonical_group,
    "place": canonical_place,
    # Events have no alias-canonicalization table (mirrors how
    # scripts/_pipeline_helpers.process_page sets an Event node's
    # canonical_name straight from its label) — the label itself is used.
    "event": lambda name: name,
}

_NODE_TYPE_FOR = {
    "person": NodeType.PERSON,
    "group": NodeType.GROUP,
    "place": NodeType.PLACE,
    "event": NodeType.EVENT,
}

# Every disambiguated canonical person name the resolver can produce, e.g.
# "richard moon (aikido)". Used to decide whether a lead's plain subject name
# ("Richard Moon") resolved to one of several same-named people, so the node
# label can say which one.
HOMONYM_CANONICALS: frozenset[str] = frozenset(
    canonical
    for variants in HOMONYM_DISAMBIGUATION.values()
    for canonical in variants.values()
)


def _display_label(canonical: str) -> str:
    """Human-readable label for a disambiguated canonical name.

    ``"richard moon (aikido)"`` -> ``"Richard Moon (aikido)"``: the name is
    title-cased, the parenthetical disambiguator left as written.
    """
    name, _, qualifier = canonical.partition(" (")
    return f"{name.title()} ({qualifier}" if qualifier else name.title()


_RELATION_SEARCH_PHRASE: dict[RelationType, str] = {
    RelationType.WORKED_AT: "worked at",
    RelationType.FOUNDED: "founded",
    RelationType.MEMBER_OF: "member of",
    RelationType.LIVED_AT: "lived at",
    RelationType.PRECEDES: "before",
    RelationType.CREATED: "created",
}


@dataclass(frozen=True)
class ResearchLead:
    """One targeted (subject, relation, object) claim to corroborate.

    Most leads originate from kkron's own first-hand account: set
    ``kkron_claim_text``/``kkron_confidence`` for those. ``kkron_confidence``
    is kkron's own stated certainty (0-1) in his first-hand account; it is
    clamped down by :func:`effective_kkron_confidence` before being stored,
    since it is not yet independently verified.

    A lead can instead originate from an already-known cited source (e.g. a
    specific claim spotted in one of the project's configured seed URLs,
    rather than kkron's own word) — set ``source_url``/``source_claim_text``/
    ``source_confidence`` for those and leave ``kkron_claim_text``/
    ``kkron_confidence`` at their defaults. This is a *different* provenance
    from kkron's personal testimony, so it is stored via a separate path
    (see :func:`build_citation_claim_record`/:func:`store_kkron_claim`) that
    does not run the confidence through the kkron-specific ceiling and does
    not attribute the claim to kkron.

    ``subject_group_type``/``object_group_type`` are optional hints (e.g.
    "restaurant") merged into the Group node's metadata when the entity is
    created.
    """

    subject_name: str
    subject_type: str  # "person" | "group" | "place" | "event"
    relation: RelationType
    object_name: str
    object_type: str  # "person" | "group" | "place" | "event"
    kkron_claim_text: str
    kkron_confidence: float
    subject_group_type: Optional[str] = None
    object_group_type: Optional[str] = None
    extra_queries: tuple[str, ...] = field(default_factory=tuple)
    # Set these three (instead of kkron_claim_text/kkron_confidence) for a
    # lead sourced from an already-known citation rather than kkron himself.
    source_url: Optional[str] = None
    source_claim_text: Optional[str] = None
    source_confidence: Optional[float] = None

    def subject_id(self) -> str:
        return _ENTITY_ID_FN[self.subject_type](self.subject_name)

    def object_id(self) -> str:
        return _ENTITY_ID_FN[self.object_type](self.object_name)

    def lead_key(self) -> str:
        """Stable identifier for this lead, used to build the claim id."""
        return stable_hash(f"{self.subject_name}|{self.relation.value}|{self.object_name}")


# ---------------------------------------------------------------------------
# Seed leads, per kkron (project owner) first-hand account, 2026-08-23 Slack
# thread. Edit this list to add/remove targeted research targets — no other
# code changes are required for a new lead to be picked up by
# scripts/03_targeted_entity_research.py.
# ---------------------------------------------------------------------------
DEFAULT_LEADS: list[ResearchLead] = [
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="The Source",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states he knows Richard Moon personally and has confirmed "
            "that Richard Moon worked at The Source restaurant on the Sunset "
            "Strip, during Jim Baker (Father Yod)'s Source Family era."
        ),
        kkron_confidence=0.75,
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Aware Inn",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states he knows Richard Moon personally and has confirmed "
            "that Richard Moon also worked at the Aware Inn, a restaurant "
            "associated with Jim Baker."
        ),
        kkron_confidence=0.75,
        extra_queries=('"Richard Moon" "Aware Inn" restaurant',),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.FOUNDED,
        object_name="Aware Inn",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states that Jim Baker (Father Yod) ran the Aware Inn "
            "restaurant."
        ),
        kkron_confidence=0.7,
        extra_queries=('"Aware Inn" "Jim Baker" OR "Father Yod"',),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.FOUNDED,
        object_name="The Source",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron reaffirms that Jim Baker (Father Yod) founded The Source "
            "restaurant on the Sunset Strip."
        ),
        kkron_confidence=0.85,
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Wild Mountain Cafe",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron says, with less certainty than the other leads here, "
            "that he believes some Wild Mountain Cafe locations are also "
            "linked to Richard Moon's history with the Source Family circle."
        ),
        kkron_confidence=0.35,
        extra_queries=(
            '"Richard Moon" "Wild Mountain Cafe"',
            '"Wild Mountain Cafe" "Source Family" OR "Father Yod"',
        ),
    ),
    # ---------------------------------------------------------------------
    # ---------------------------------------------------------------------
    # kkron's central hypothesis for this thread: that Richard Moon is the
    # person who introduced Jim Baker to Yogi Bhajan, and that this meeting
    # is what set Baker on the road to becoming Father Yod.
    #
    # This lead was previously mis-filed. It used to be stored as three
    # *citation*-sourced claims attributed to pleasekillme.com's Father Yod
    # profile, asserting "a March 1971 meeting of Richard Moon, Father Yod,
    # and Yogi Bhajan". Re-reading that article (Amanda Sheppard,
    # 18 September 2018) shows it says no such thing: it never mentions any
    # Moon, and its March 1971 passage is about Baker resolving to become a
    # spiritual leader after the 90-day India trip he took with Yogi Bhajan
    # and 83 other 3HO students. The introduction hypothesis is kkron's, so
    # it belongs on the kkron path at capped confidence — not dressed up as
    # something a published article reported. See
    # docs/journalistic_sources_2026-08-24.md.
    # ---------------------------------------------------------------------
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MENTIONS,
        # Deliberately the label of the Event node the crawl already
        # produced (from grokipedia, dated May 1969), not a new
        # "Introduction of..." label — event_id() slugifies the label, so a
        # near-synonym would fork the same real meeting into two nodes and
        # the contradiction detector would never relate kkron's account to
        # the crawled facts about it.
        object_name="Meeting of Baker and Yogi Bhajan",
        object_type="event",
        kkron_claim_text=(
            "kkron states that Richard Moon introduced Jim Baker (later "
            "Father Yod) to Yogi Bhajan, and that many people regard that "
            "meeting as the start of Baker's transformation into Father "
            "Yod. No journalistic source found to date names who made the "
            "introduction; see docs/journalistic_sources_2026-08-24.md."
        ),
        kkron_confidence=0.6,
        extra_queries=(
            '"Richard Moon" introduced "Jim Baker" "Yogi Bhajan"',
            '"Father Yod" "Yogi Bhajan" who introduced them first met 1969',
            '"Aware Inn" "Yogi Bhajan" 1969 introduced Baker student',
        ),
    ),
    # ---------------------------------------------------------------------
    # Citation-sourced leads (not kkron's own account): what the published
    # record *does* say about Baker and Yogi Bhajan. These are the accurate
    # replacements for the withdrawn "March 1971 meeting" claims — same
    # underlying question (how close were Baker and Bhajan, and when), but
    # quoted from sources that actually say it.
    # ---------------------------------------------------------------------
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="3HO",
        object_type="group",
        object_group_type="spiritual_organization",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url=(
            "https://escholarship.org/content/qt6r63q6qn/"
            "qt6r63q6qn_noSplash_fbbba186685c0619c35208f88b1f29ec.pdf"
        ),
        source_claim_text=(
            "Philip Deslippe, 'From Maharaj to Mahan Tantric: The "
            "Construction of Yogi Bhajan's Kundalini Yoga', Sikh Formations "
            "8(3), December 2012, pp. 369-387, states: 'Yogi Bhajan told Jim "
            "Baker, one of his senior students in Los Angeles, to come on "
            "the trip for the purpose of getting the blessing of his "
            "teacher', citing Isis Aquarian ed., The Source (Process Media, "
            "2007), p. 46. This is the strongest peer-reviewed source "
            "placing Baker among Yogi Bhajan's senior Los Angeles students."
        ),
        source_confidence=0.85,
        extra_queries=(
            'Deslippe "Yogi Bhajan" "Jim Baker" senior students Los Angeles',
        ),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="1970-1971 3HO pilgrimage to India led by Yogi Bhajan",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://pleasekillme.com/father-yod/",
        source_claim_text=(
            "Amanda Sheppard, 'Father Yod: War Hero, Bank Robber, Polygamist "
            "Cult Leader and Psychedelic Recording Artist!', Please Kill Me, "
            "18 September 2018, states: 'In March 1971, Jim Baker decided "
            "that it was his destiny to become a spiritual leader. This came "
            "to him in the wake of a disastrous 90-day trip to India with 83 "
            "of his fellow 3HO yoga students and Yogi Bhajan.' The article "
            "does not mention Richard Moon, and does not describe a meeting "
            "of Moon, Baker and Bhajan."
        ),
        source_confidence=0.55,
        extra_queries=(
            '"Father Yod" India trip 1971 "Yogi Bhajan" 3HO students 90 days',
        ),
    ),
    ResearchLead(
        subject_name="Yogi Bhajan",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="1970-1971 3HO pilgrimage to India led by Yogi Bhajan",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        # Anchored to Deslippe's PDF, the page actually read — not to a
        # constructed washingtonpost.com URL that has never been fetched.
        # A source_url is a provenance assertion: it has to point at
        # something that demonstrably says this. Deslippe's bibliography
        # does; a guessed archive URL might 404.
        source_url=(
            "https://escholarship.org/content/qt6r63q6qn/"
            "qt6r63q6qn_noSplash_fbbba186685c0619c35208f88b1f29ec.pdf"
        ),
        source_claim_text=(
            "Deslippe (2012) cites, and quotes for the trip's stated "
            "purpose, a contemporaneous newspaper report: William L. "
            "Claiborne, 'Yoga students set India trip for drug study', The "
            "Washington Post, 23 December 1970, p. B2. Per Deslippe, Yogi "
            "Bhajan told the reporter the group was on a fact-finding "
            "mission in India to research how best to get the youth of "
            "America off drugs via yoga. The Post article itself has not "
            "been retrieved — this claim is about what Deslippe's "
            "bibliography records, not about text read in the Post."
        ),
        source_confidence=0.5,
        extra_queries=(
            'Claiborne 1970 "Yoga students set India trip for drug study" Washington Post',
        ),
    ),
    ResearchLead(
        subject_name="Yogi Bhajan",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Yogi Bhajan teaching Kundalini Yoga in Los Angeles 1968-1971",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        # Anchored to Deslippe's PDF for the same reason as the lead above:
        # latimes.com's homepage does not assert anything about a 1969
        # article, and the archived article itself is paywalled and unread.
        source_url=(
            "https://escholarship.org/content/qt6r63q6qn/"
            "qt6r63q6qn_noSplash_fbbba186685c0619c35208f88b1f29ec.pdf"
        ),
        source_claim_text=(
            "Deslippe (2012) cites Marty Altschul, 'Tense housewives, "
            "businessmen try relaxing Hindu way', Los Angeles Times, 22 "
            "June 1969 — the earliest contemporaneous Los Angeles Times "
            "coverage of Yogi Bhajan teaching in Los Angeles located so "
            "far — for Yogi Bhajan's shifting account of how long he had "
            "studied yoga. The LA Times article is behind the paper's "
            "historical archive / ProQuest and has not been retrieved: this "
            "claim is about what Deslippe's bibliography records, not about "
            "text read in the Times."
        ),
        source_confidence=0.5,
        extra_queries=(
            'Altschul "Tense housewives, businessmen try relaxing Hindu way" 1969',
            '"Yogi Bhajan" "Los Angeles Times" 1969 kundalini yoga class',
        ),
    ),
    # ---------------------------------------------------------------------
    # Second thread (2026-08-24 research brief): Richard Moon's 1990s
    # conflict-resolution work in Cyprus, and the hypothesis that Doug Stone
    # was employed by the Cyprus Fulbright Commission to train the Cyprus
    # Conflict Resolution Trainers Group. This thread is outside the Source
    # Family subject matter, but it is about the same Richard Moon, and it
    # is what makes the aikido Moon distinguishable from his two namesakes
    # — see HOMONYM_DISAMBIGUATION in src/extractor/alias_resolver.py.
    # ---------------------------------------------------------------------
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="Institute for Multi-Track Diplomacy",
        object_type="group",
        object_group_type="ngo",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://openmindadventures.com/richard-moon/",
        source_claim_text=(
            "Richard Moon's own published biography states: 'He has been "
            "involved in international peace-building, having worked in "
            "Cyprus and Bosnia under the auspices of the Institute for "
            "Multi-Track Diplomacy, in association with the Fulbright "
            "Commission, the American Embassy in Cyprus, Conflict "
            "Management Group and the Harvard Negotiation Project.' This is "
            "self-published autobiography, not journalism, and no "
            "independent source found to date names Moon on a Cyprus "
            "Consortium or CRTG roster."
        ),
        source_confidence=0.45,
        extra_queries=(
            '"Richard Moon" aikido Cyprus "Multi-Track Diplomacy" peace building',
            '"Richard Moon" Cyprus Fulbright conflict resolution trainer 1990s',
        ),
    ),
    ResearchLead(
        subject_name="Cyprus Consortium",
        subject_type="group",
        subject_group_type="ngo",
        relation=RelationType.MEMBER_OF,
        object_name="Cyprus Fulbright Commission",
        object_type="group",
        object_group_type="binational_commission",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://cyprusreview.org/index.php/cr/article/download/490/438",
        source_claim_text=(
            "Benjamin J. Broome, 'Overview of Conflict Resolution Activities "
            "in Cyprus: Their Contribution to the Peace Process', The Cyprus "
            "Review 10(1), 1998, pp. 47-66, states: 'a number of conflict "
            "resolution workshops were held in the summer of 1994 organized "
            "by the Cyprus Fulbright Commission (CFC) and conducted by the "
            "Cyprus Consortium, a group that consists of IMTD, the Conflict "
            "Management Group (CMG) of Harvard University, and National "
            "Training Laboratory (NTL) based in Virginia. The team leaders "
            "for this effort were Louise Diamond and her colleague Diana "
            "Chigas (from CMG). Funded by U.S. Agency for International "
            "Development and administered by CFC...'. Broome names no Doug "
            "Stone anywhere in the paper."
        ),
        source_confidence=0.9,
        extra_queries=(
            'Broome 1998 "Cyprus Review" conflict resolution activities consortium',
        ),
    ),
    ResearchLead(
        subject_name="Doug Stone",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Cyprus Fulbright Commission",
        object_type="group",
        object_group_type="binational_commission",
        kkron_claim_text=(
            "Superseded framing, kept because the question was asked and "
            "answered. Doug Stone was NOT employed or formally appointed by "
            "the Cyprus Fulbright Commission: he appears in none of the "
            "Cyprus rosters found (Broome 1998, the CRTG Wikipedia article, "
            "the Future Worlds Center wiki), and the four named Fulbright "
            "Scholars in Conflict Resolution are Broome, Philip Snyder, "
            "John Ungerleider and Marco Turk. kkron subsequently reports "
            "(2026-08-25) that Stone confirmed to him the actual route in: "
            "Diana Chigas recruited him. That is a different and better-"
            "fitting mechanism — see the 'Doug Stone MEMBER_OF Cyprus "
            "Consortium' lead — and it is consistent with Broome 1998, "
            "which names Chigas (of CMG) as a Cyprus Consortium team "
            "leader. See docs/journalistic_sources_2026-08-24.md."
        ),
        kkron_confidence=0.15,
        extra_queries=(
            '"Doug Stone" OR "Douglas Stone" "Cyprus Fulbright Commission"',
            '"Douglas Stone" Cyprus conflict resolution trainers group 1990s',
            '"Conflict Management Group" Cyprus team roster "Stone"',
        ),
    ),
    # ---------------------------------------------------------------------
    # 2026-08-25. kkron reports back from interviews he conducted himself
    # (Richard Moon, Doug Stone) and from correspondence with Keith E.
    # Peterson, author of "American Dreams: The Story of the Cyprus
    # Fulbright Commission" (Armida Books, 2024).
    #
    # Provenance discipline, which is the whole point of this file: a lead
    # gets a source_url ONLY where the URL is a document that has been read
    # and demonstrably says the thing. kkron's report of what a person told
    # him, or of what a book he holds contains, is kkron-path — real signal,
    # capped, and honestly labelled as second-hand attribution. Two of the
    # leads below cleared the citation bar; the rest did not, and are filed
    # accordingly rather than dressed up.
    # ---------------------------------------------------------------------
    ResearchLead(
        subject_name="Christopher Thorsen",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Cyprus Fulbright Commission",
        object_type="group",
        object_group_type="binational_commission",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://openmindadventures.com/chris-thorsen/",
        source_claim_text=(
            "Christopher (Chris) Thorsen's own published biography states: "
            "'In the late nineties, Chris spent five years providing "
            "periodic Aikido/Conflict Resolution Seminars for policy "
            "leaders from the Turkish and Greek factions on the war torn "
            "Island of Cyprus.' It names no sponsor — not the Fulbright "
            "Commission, not the Cyprus Consortium, not IMTD — so the "
            "employing body is Thorsen's-account-silent and this edge "
            "records the programme he describes, not a contract. Note the "
            "date tension with the kkron-reported 2008 case study, which "
            "has him hired in 1995: 'late nineties' plus five years reads "
            "as roughly 1996-2001. Both are stored as stated; neither is "
            "reconciled. Self-published autobiography, not journalism."
        ),
        source_confidence=0.45,
        extra_queries=(
            '"Chris Thorsen" OR "Christopher Thorsen" Cyprus aikido seminars policy leaders',
            '"Thorsen" "Cyprus Consortium" OR "Cyprus Fulbright" aikido trainer',
        ),
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        # person MENTIONS event, matching how the other association leads in
        # this file are modelled — there is no COLLABORATED_WITH relation,
        # and MEMBER_OF person->person would assert something false.
        relation=RelationType.MENTIONS,
        object_name="Peace-building initiatives of Richard Moon with Louise Diamond",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url=(
            "https://thetaichinotebook.com/2026/01/31/"
            "the-first-podcast-of-2026-quantum-aikido-with-richard-moon/"
        ),
        source_claim_text=(
            "The Tai Chi Notebook podcast episode notes, 31 January 2026, "
            "state: 'Richard Moon describes developing a \"very freestyle, "
            "jazz-oriented approach\" to Aikido, which eventually led to "
            "corporate coaching with Chris Thorsen and international peace "
            "building initiatives with Louise Diamond and a $30 million "
            "project in Bosnia funded by Dan Whalen.' This is the first "
            "source found for Moon's peace-building work that is NOT "
            "self-published — a third party's account of an interview — and "
            "it independently links Moon both to Louise Diamond (whom "
            "Broome 1998 names as a Cyprus Consortium team leader) and to "
            "Chris Thorsen. It says nothing about Cyprus, the Fulbright "
            "Commission, Los Angeles, The Source, Jim Baker or Yogi Bhajan; "
            "none of those words appears on the page."
        ),
        source_confidence=0.6,
        extra_queries=(
            '"Richard Moon" "Louise Diamond" aikido peace building Bosnia',
            '"Richard Moon" "Chris Thorsen" aikido consulting',
        ),
    ),
    ResearchLead(
        subject_name="Doug Stone",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="Cyprus Consortium",
        object_type="group",
        object_group_type="ngo",
        kkron_claim_text=(
            "kkron reports (2026-08-25) that Doug Stone confirmed to him "
            "that Diana Chigas recruited him for the Cyprus work. This is "
            "kkron's second-hand report of what Stone said, not a document "
            "read, so it is stored on the kkron path — but it fits the "
            "documented structure exactly: Broome 1998 names Chigas, of the "
            "Conflict Management Group, as one of the two Cyprus Consortium "
            "team leaders alongside Louise Diamond, and CMG is a Consortium "
            "member. Recruitment onto a CMG/Consortium team is a different "
            "claim from employment by the Cyprus Fulbright Commission, "
            "which remains unsupported. Corroborate by finding Stone named "
            "on a CMG or Consortium roster."
        ),
        kkron_confidence=0.5,
        extra_queries=(
            '"Doug Stone" OR "Douglas Stone" "Diana Chigas" Cyprus',
            '"Conflict Management Group" Cyprus team 1990s Stone Chigas roster',
        ),
    ),
    ResearchLead(
        subject_name="Christopher Thorsen",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="Cyprus Consortium",
        object_type="group",
        object_group_type="ngo",
        kkron_claim_text=(
            "kkron reports (2026-08-25) that a 2008 case study records "
            "Chris Thorsen as hired by the Cyprus Consortium in 1995 under "
            "the title 'Aikido'. OPEN LEAD: the case study has not been "
            "located — searches for a 2008 Cyprus bicommunal case study "
            "naming Thorsen or an Aikido training returned nothing, so this "
            "records what kkron reports the study says, and carries no "
            "source_url until the document is in hand. It also sits in "
            "tension with Thorsen's own bio ('late nineties', five years, "
            "so roughly 1996-2001); both dates are stored as stated."
        ),
        kkron_confidence=0.4,
        extra_queries=(
            '2008 case study Cyprus bicommunal trainers "Aikido" Thorsen 1995',
            'Laouris OR Hadjipavlou OR Broome 2008 Cyprus case study aikido training 1995',
            '"Cyprus Consortium" 1995 trainers hired aikido',
        ),
    ),
    ResearchLead(
        subject_name="Louise Diamond",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Recruitment of Richard Moon and Christopher Thorsen into the Cyprus Fulbright conflict-resolution programme",
        object_type="event",
        kkron_claim_text=(
            "kkron reports (2026-08-25) that Keith E. Peterson's book "
            "'American Dreams: The Story of the Cyprus Fulbright "
            "Commission' (Armida Books, 2024) attributes to Louise Diamond "
            "the bringing of Aikido instructor Richard Moon and his "
            "colleague Christopher Thorsen into the Cyprus Fulbright "
            "Commission's conflict-resolution and peace-building work, and "
            "describes them working with Cypriot participants. This is "
            "PROPOSED attribution text kkron is drafting for editorial "
            "review, not a verified quotation: no page or verbatim passage "
            "from the book has been supplied, so there is no source_url to "
            "the book. kkron's own framing is explicit that the account "
            "does NOT establish that either man was a member of the Cyprus "
            "Conflict Resolution Trainers Group — and no MEMBER_OF edge to "
            "the CRTG is created for either, consistent with Broome 1998 "
            "and both roster sources, in which neither name appears."
        ),
        kkron_confidence=0.45,
        extra_queries=(
            'Peterson "American Dreams" Cyprus Fulbright "Richard Moon" OR "Thorsen" aikido',
            '"Louise Diamond" recruited aikido instructors Cyprus Fulbright conflict resolution',
        ),
    ),
    ResearchLead(
        subject_name="Keith E. Peterson",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Christopher Thorsen",
        object_type="person",
        kkron_claim_text=(
            "kkron reports (2026-08-25) receiving email correspondence from "
            "Keith E. Peterson, author of 'American Dreams: The Story of "
            "the Cyprus Fulbright Commission' (Armida Books, 2024), in "
            "which Peterson states he remembers at least one conversation "
            "with Mr. Thorsen; that he recorded and transcribed all 180 "
            "interviews he conducted for the book but archived every voice "
            "file, document, email and photo to a storage device about a "
            "year ago, so retrieval would not currently be easy; that he "
            "acknowledges the Moon citation in his book; and that he "
            "acknowledges an error kkron reported to him, the second or "
            "third found since publication. IMPORTANT: in the same email "
            "Peterson explicitly DECLINES to discuss Richard Moon's work. "
            "The email therefore corroborates that Thorsen was among his "
            "interviewees — it is not Peterson confirming anything about "
            "Moon or Doug Stone. Only the research-bearing content is "
            "recorded here; personal matters in the email are deliberately "
            "omitted from this public graph."
        ),
        kkron_confidence=0.5,
        extra_queries=(
            'Peterson "American Dreams" Cyprus Fulbright Commission interviews Thorsen',
        ),
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Interview of Richard Moon by kkron",
        object_type="event",
        kkron_claim_text=(
            "kkron reports (2026-08-25) that he interviewed Richard Moon "
            "and that Moon confirmed kkron's assertions about his own "
            "history — the Source restaurant and Aware Inn work, and the "
            "introduction of Jim Baker to Yogi Bhajan. This claim records "
            "the confirmation event; the underlying assertions remain "
            "stored as the existing kkron leads rather than being "
            "duplicated. Provenance caveat that does not go away: Moon "
            "confirming claims about Moon is first-person testimony from "
            "the subject, which is real signal but is not independent "
            "corroboration, and no transcript has been supplied. Nothing "
            "here upgrades the Source Family claims to journalistically "
            "confirmed — no published source found names Moon in "
            "connection with The Source, Jim Baker or Yogi Bhajan. Supply "
            "the transcript to store what Moon actually said, in his own "
            "words, attributed to him as speaker."
        ),
        kkron_confidence=0.5,
        extra_queries=(
            '"Richard Moon" aikido interview "The Source" OR "Father Yod" restaurant Los Angeles',
        ),
    ),
]


def lead_search_priority(lead: ResearchLead) -> float:
    """Priority score for search ordering — higher = search first.

    The tiered search strategy uses free-tier Gemini quota first, so the
    leads with the most to gain from independent corroboration should be
    searched first (while free quota is still available). The score is:

    - **High kkron confidence + not yet corroborated** = highest priority.
      These are the leads where independent corroboration would produce
      the biggest confidence jump (from capped 0.5 to uncapped ~1.0).
    - **Citation-sourced leads** (source_url set) get a moderate priority:
      they already have one cited source, so additional corroboration is
      valuable but less critical than an uncorroborated first-hand claim.
    - **Low kkron confidence** (e.g. Wild Mountain Cafe at 0.35) gets
      lower priority — less likely to find anything, and the confidence
      gain is smaller even if found.
    """
    # Citation-sourced leads: moderate priority based on source_confidence.
    if lead.source_url is not None:
        return 0.3 + (lead.source_confidence or 0.4) * 0.2  # 0.38-0.50

    # kkron-sourced leads: priority proportional to raw confidence.
    # Higher confidence = more to gain from corroboration.
    return lead.kkron_confidence


def sort_leads_by_priority(
    leads: list[ResearchLead],
    *,
    free_quota_leads: Optional[int] = None,
) -> list[ResearchLead]:
    """Sort leads so the highest-value-for-corroboration leads come first.

    If ``free_quota_leads`` is given (e.g. estimated number of leads that
    can be searched with remaining free-tier quota), the sort ensures
    those leads get the highest-priority ones. Leads beyond the free
    quota will be searched via the paid tier, so the lowest-priority
    leads end up there (minimizing paid cost).
    """
    return sorted(leads, key=lead_search_priority, reverse=True)


def effective_kkron_confidence(raw_confidence: float) -> float:
    """Clamp a kkron first-hand confidence into [0, KKRON_CONFIDENCE_CEILING].

    Ensures a first-hand, not-yet-independently-corroborated account never
    scores as high as (or higher than) a claim extracted from a real,
    independently found web source.
    """
    return max(0.0, min(raw_confidence, KKRON_CONFIDENCE_CEILING))


def build_search_queries(lead: ResearchLead) -> list[str]:
    """Build a de-duplicated list of web search queries for a lead.

    Hand-tuned ``extra_queries`` (usually the most targeted) come first,
    followed by a generic "<subject> <relation phrase> <object>" query and a
    quoted co-occurrence query.
    """
    phrase = _RELATION_SEARCH_PHRASE.get(lead.relation, "connected to")
    candidates = [
        *lead.extra_queries,
        f"{lead.subject_name} {phrase} {lead.object_name}",
        f'"{lead.subject_name}" "{lead.object_name}"',
    ]
    seen: set[str] = set()
    queries: list[str] = []
    for q in candidates:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            queries.append(q.strip())
    return queries


def build_kkron_claim_record(lead: ResearchLead) -> dict:
    """Build the claim dict for a lead's sourced claim.

    Delegates to :func:`build_citation_claim_record` for a lead sourced from
    an already-known citation (``lead.source_url`` set) rather than kkron's
    own first-hand account — see :class:`ResearchLead`.

    Shape mirrors the enriched claim dicts produced by
    ``GeminiClaimExtractor.extract_claims`` / ``ClaimExtractor.extract_claims``
    (id, claim_text, claim_type, stance, confidence, speaker, speaker_id,
    evidence_mode, source_url) so it stores the same way any other claim
    does; see :func:`store_kkron_claim`.
    """
    if lead.source_url:
        return build_citation_claim_record(lead)
    cid = f"claim:kkron:{lead.lead_key()}"
    return {
        "id": cid,
        "claim_text": lead.kkron_claim_text,
        "claim_type": ClaimType.BIOGRAPHICAL.value,
        "stance": ClaimStance.NEUTRAL.value,
        "confidence": effective_kkron_confidence(lead.kkron_confidence),
        "raw_kkron_confidence": lead.kkron_confidence,
        "evidence_mode": EvidenceMode.FIRST_PERSON.value,
        "speaker": KKRON_SOURCE_LABEL,
        "speaker_id": KKRON_SOURCE_PERSON_ID,
        "source_url": KKRON_SOURCE_URL,
    }


def build_citation_claim_record(lead: ResearchLead) -> dict:
    """Build the claim dict for a lead sourced from an already-known cited
    URL (``lead.source_url``) rather than kkron's own first-hand account.

    Unlike :func:`build_kkron_claim_record`'s kkron path, ``source_confidence``
    is stored as-is — it is *not* run through :func:`effective_kkron_confidence`
    / ``KKRON_CONFIDENCE_CEILING``, since that ceiling exists specifically to
    keep kkron's own unverified word from outranking independently found
    claims. A citation claim has no ``speaker``/``speaker_id`` (it is not
    attributed to a person asserting it first-hand); see
    :func:`ensure_citation_source`/:func:`store_kkron_claim` for how it is
    linked to its source instead (SUPPORTED_BY, not ASSERTED_BY).
    """
    cid = f"claim:citation:{lead.lead_key()}"
    return {
        "id": cid,
        "claim_text": lead.source_claim_text,
        "claim_type": ClaimType.BIOGRAPHICAL.value,
        "stance": ClaimStance.NEUTRAL.value,
        "confidence": lead.source_confidence,
        "raw_kkron_confidence": None,
        "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
        "speaker": None,
        "speaker_id": None,
        "source_url": lead.source_url,
    }


def filter_new_urls(urls: list[str], already_known: set[str]) -> list[str]:
    """Drop URLs already present in ``already_known`` (e.g. existing DB
    sources), de-duplicating the remainder while preserving order."""
    seen: set[str] = set(already_known)
    out: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# DB-writing helpers (no network calls) — store kkron's first-hand claims.
# ---------------------------------------------------------------------------


def ensure_kkron_source(db: GraphDB) -> None:
    """Idempotently create the Person node + pseudo Work/Source record that
    represent kkron himself as the asserter of his first-hand claims.

    Mirrors how scripts/_pipeline_helpers.process_page creates a Work node +
    SourceRecord for every crawled page, and how scripts/02_gemini_search.py
    uses a non-http pseudo-URL (``gemini://inline-text``) for inline text
    that has no real source URL.
    """
    db.add_node(GraphNode(
        id=KKRON_SOURCE_PERSON_ID,
        type=NodeType.PERSON,
        label=KKRON_SOURCE_LABEL,
        canonical_name=KKRON_SOURCE_LABEL,
        metadata={
            "role": "project_owner_source",
            "note": (
                "Project owner's first-hand personal account. Claims "
                f"ASSERTED_BY this node are capped at confidence <= "
                f"{KKRON_CONFIDENCE_CEILING} until independently "
                "corroborated by scripts/03_targeted_entity_research.py."
            ),
        },
        source_urls=[KKRON_SOURCE_URL],
    ))
    db.add_node(GraphNode(
        id=KKRON_WORK_ID,
        type=NodeType.WORK,
        label="kkron — personal communication (project owner)",
        canonical_name=None,
        metadata={
            "url": KKRON_SOURCE_URL,
            "platform": "kkron (personal communication)",
            "work_type": "personal_communication",
        },
        source_urls=[KKRON_SOURCE_URL],
    ))
    db.add_source(SourceRecord(
        id=KKRON_WORK_ID,
        url=KKRON_SOURCE_URL,
        title="kkron — personal communication (project owner)",
        author="kkron",
        platform="kkron (personal communication)",
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))


def ensure_citation_source(db: GraphDB, lead: ResearchLead) -> str:
    """Idempotently create the Work/Source record for a lead's cited URL
    (``lead.source_url``) that has not yet been fetched/extracted by the
    crawl pipeline.

    Mirrors how scripts/_pipeline_helpers.process_page creates a Work node +
    SourceRecord for every crawled page. If that URL is later actually
    crawled (e.g. it's already a project seed URL, per README), that crawl's
    ``process_page`` call upserts the same Work/Source id — this placeholder
    just makes sure the citation exists in the graph now, before any crawl
    runs. Returns the Work node id.
    """
    wid = work_id(lead.source_url)
    db.add_node(GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=f"cited source: {lead.source_url}",
        canonical_name=None,
        metadata={
            "url": lead.source_url,
            "platform": get_domain(lead.source_url),
            "work_type": "web_page",
        },
        source_urls=[lead.source_url],
    ))
    db.add_source(SourceRecord(
        id=wid,
        url=lead.source_url,
        title=None,
        author=None,
        platform=get_domain(lead.source_url),
        source_class=SourceClass.JOURNALISTIC,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))
    return wid


def _ensure_entity_node(
    db: GraphDB,
    name: str,
    entity_type: str,
    group_type: Optional[str],
    source_url: str = KKRON_SOURCE_URL,
) -> str:
    node_id = _ENTITY_ID_FN[entity_type](name)
    canonical = _CANONICAL_FN[entity_type](name)
    metadata = {"group_type": group_type} if (entity_type == "group" and group_type) else {}
    # A lead names a person the way a human would ("Richard Moon"), but three
    # unrelated people answer to that name in this graph. Where the resolver
    # disambiguated the name, show the disambiguated form as the label too —
    # otherwise re-running a lead would keep overwriting the split node's
    # label with the bare name it was split apart to stop asserting. See
    # HOMONYM_DISAMBIGUATION in src/extractor/alias_resolver.py.
    label = name
    if entity_type == "person" and canonical in HOMONYM_CANONICALS:
        label = _display_label(canonical)
    db.add_node(GraphNode(
        id=node_id,
        type=_NODE_TYPE_FOR[entity_type],
        label=label,
        canonical_name=canonical,
        metadata=metadata,
        source_urls=[source_url],
    ))
    return node_id


def store_kkron_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's sourced claim + its relation edge.

    Dispatches to :func:`_store_citation_claim` for a lead sourced from an
    already-known citation (``lead.source_url`` set) rather than kkron's own
    first-hand account — see :class:`ResearchLead`. Kept as a single entry
    point (same name, same call site in scripts/03_targeted_entity_research.py)
    so no other code changes are required for a new lead of either kind to be
    picked up.

    Idempotent: safe to call repeatedly (e.g. on every cron run) — node
    upserts merge metadata/labels and edge/claim-source-link inserts use
    ``INSERT OR IGNORE`` under the hood (see GraphDB), so re-running never
    duplicates data.

    Returns the claim node id.
    """
    if lead.source_url:
        return _store_citation_claim(db, lead)

    ensure_kkron_source(db)
    subject_id = _ensure_entity_node(db, lead.subject_name, lead.subject_type, lead.subject_group_type)
    object_id = _ensure_entity_node(db, lead.object_name, lead.object_type, lead.object_group_type)

    claim = build_kkron_claim_record(lead)
    cid = claim["id"]
    db.add_node(GraphNode(
        id=cid,
        type=NodeType.CLAIM,
        label=claim["claim_text"][:200],
        canonical_name=None,
        metadata={
            "claim_text": claim["claim_text"],
            "claim_type": claim["claim_type"],
            "stance": claim["stance"],
            "confidence": claim["confidence"],
            "raw_kkron_confidence": claim["raw_kkron_confidence"],
            "evidence_mode": claim["evidence_mode"],
            "pending_independent_corroboration": True,
        },
        source_urls=[KKRON_SOURCE_URL],
    ))

    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.CONTAINS, dst_id=cid,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.MENTIONS, dst_id=subject_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.MENTIONS, dst_id=object_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ASSERTED_BY, dst_id=KKRON_SOURCE_PERSON_ID,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=subject_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=object_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_claim_source_link(ClaimSourceLink(claim_id=cid, source_id=KKRON_WORK_ID))

    # The relation itself (e.g. Richard Moon WORKED_AT The Source), tagged as
    # coming from kkron's account and not yet independently verified. A
    # later independent-source relation edge with the same (src, rel, dst)
    # is a no-op thanks to the UNIQUE(src_id, rel_type, dst_id) constraint —
    # the *claim* is what carries the (lower vs. independently-verified)
    # confidence distinction, not the edge.
    db.add_edge(GraphEdge(
        src_id=subject_id,
        rel_type=lead.relation,
        dst_id=object_id,
        metadata={
            "evidence": KKRON_SOURCE_URL,
            "trigger": "kkron_first_hand_account",
            "asserted_by": "kkron",
            "verified_independently": False,
        },
    ))
    return cid


def _store_citation_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's citation-sourced claim + its relation edge.

    Counterpart to the kkron-first-hand-account body of
    :func:`store_kkron_claim`, for a lead sourced from an already-known cited
    URL (``lead.source_url``) rather than kkron's own account: the claim is
    linked to a Work/Source node for that URL (SUPPORTED_BY, not
    ASSERTED_BY — there is no first-hand speaker to name) instead of to the
    kkron Person/Work nodes, and its confidence is stored as-is (see
    :func:`build_citation_claim_record`) rather than clamped by
    ``KKRON_CONFIDENCE_CEILING``. Still marked
    ``pending_independent_corroboration`` — a citation is a lead to verify,
    not a confirmed fact, until scripts/03_targeted_entity_research.py's
    search/crawl/extraction phase finds (or fails to find) corroboration.

    Idempotent for the same reasons as :func:`store_kkron_claim`.
    """
    wid = ensure_citation_source(db, lead)
    subject_id = _ensure_entity_node(
        db, lead.subject_name, lead.subject_type, lead.subject_group_type,
        source_url=lead.source_url,
    )
    object_id = _ensure_entity_node(
        db, lead.object_name, lead.object_type, lead.object_group_type,
        source_url=lead.source_url,
    )

    claim = build_citation_claim_record(lead)
    cid = claim["id"]
    db.add_node(GraphNode(
        id=cid,
        type=NodeType.CLAIM,
        label=claim["claim_text"][:200],
        canonical_name=None,
        metadata={
            "claim_text": claim["claim_text"],
            "claim_type": claim["claim_type"],
            "stance": claim["stance"],
            "confidence": claim["confidence"],
            "evidence_mode": claim["evidence_mode"],
            "pending_independent_corroboration": True,
        },
        source_urls=[lead.source_url],
    ))

    # Work -> entity edges: DESCRIBES for an Event (mirrors
    # scripts/_pipeline_helpers.process_page), MENTIONS otherwise.
    for entity_id, entity_type in (
        (subject_id, lead.subject_type),
        (object_id, lead.object_type),
    ):
        rel = RelationType.DESCRIBES if entity_type == "event" else RelationType.MENTIONS
        db.add_edge(GraphEdge(src_id=wid, rel_type=rel, dst_id=entity_id,
                               metadata={"evidence": lead.source_url}))

    db.add_edge(GraphEdge(src_id=wid, rel_type=RelationType.CONTAINS, dst_id=cid,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.SUPPORTED_BY, dst_id=wid,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=subject_id,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=object_id,
                           metadata={"evidence": lead.source_url}))
    db.add_claim_source_link(ClaimSourceLink(claim_id=cid, source_id=wid))

    # The relation itself (e.g. Richard Moon MENTIONS <the March 1971
    # meeting event>), tagged as coming from the cited source and not yet
    # independently verified.
    db.add_edge(GraphEdge(
        src_id=subject_id,
        rel_type=lead.relation,
        dst_id=object_id,
        metadata={
            "evidence": lead.source_url,
            "trigger": "cited_source_lead",
            "asserted_by": "cited_source",
            "verified_independently": False,
        },
    ))
    return cid
