"""
Entity extraction: spaCy NER + rule-based patterns for Source Family corpus.
Falls back to rule-based only if spaCy is not available.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from src.extractor.alias_resolver import (
    ALIAS_MAP,
    KNOWN_PERSONS,
    KNOWN_GROUPS,
    KNOWN_PLACES,
    is_aquarian_name,
    canonical_person,
)
from src.utils.text_utils import normalize, split_sentences, extract_date_from_text

_log = logging.getLogger(__name__)

# Rule-based person patterns (regex)
PERSON_PATTERNS = [
    r"\bFather\s+Yod\b",
    r"\bJim\s+Baker\b",
    r"\bJames\s+(Edward\s+)?Baker\b",
    r"\bLaura\s+Garon\b",
    r"\bIsis\s+Aquarian\b",
    r"\bDjin\s+Aquarian\b",
    r"\bRhythm\s+Aquarian\b",
    r"\bHom\s+Aquarian\b",
    r"\bOctavius\b",
    r"\b[A-Z][a-z]+\s+Aquarian\b",  # Any "X Aquarian" name
]

# Group patterns
GROUP_PATTERNS = [
    r"\bThe\s+Source\s+Family\b",
    r"\bSource\s+Family\b",
    r"\bThe\s+Source\s+Restaurant\b",
    r"\bThe\s+Source\b(?!\s+Family)(?!\s+Restaurant)",
    r"\bYa\s+Ho\s+Wa\s+13\b",
    r"\bYahowha\s+13\b",
]

# Place patterns
PLACE_PATTERNS = [
    r"\bSunset\s+Strip\b",
    r"\bKauai\b",
    r"\bNichols\s+Canyon\b",
    r"\bFairmont\s+Hotel\b",
    r"\bLos\s+Angeles\b",
    r"\bSan\s+Francisco\b",
]

# Event trigger verbs
EVENT_TRIGGERS = [
    "opened", "founded", "moved to", "sold the restaurant",
    "died", "closed", "started", "joined", "left",
]

# Claim trigger verbs
CLAIM_TRIGGERS = [
    "said", "claimed", "described", "argued", "remembered",
    "denied", "insisted", "compared", "wrote", "stated",
    "recalled", "alleged", "reported", "asserted", "maintained",
]


class EntityExtractor:
    """Hybrid NER + rule-based entity extractor."""

    def __init__(self, spacy_model_name: str = "en_core_web_sm"):
        self._nlp = None
        self._spacy_model_name = spacy_model_name
        self._try_load_spacy(spacy_model_name)

    def _try_load_spacy(self, model_name: str):
        """Attempt to load spaCy model; fall back to rules only."""
        try:
            import spacy
            self._nlp = spacy.load(model_name)
            _log.info(f"Loaded spaCy model: {model_name}")
        except Exception as e:
            _log.warning(f"spaCy model '{model_name}' not available ({e}); using rule-based extraction only")
            self._nlp = None

    def extract(self, text: str) -> dict:
        """Extract entities from text.
        Returns dict with keys: persons, groups, places, events, claims.
        """
        persons = self._extract_persons(text)
        groups = self._extract_groups(text)
        places = self._extract_places(text)
        events = self._extract_events(text)
        claims = self._extract_claims(text)

        return {
            "persons": persons,
            "groups": groups,
            "places": places,
            "events": events,
            "claims": claims,
        }

    def _extract_persons(self, text: str) -> list[dict]:
        """Extract person entities."""
        persons = {}

        # Rule-based patterns
        for pattern in PERSON_PATTERNS:
            for match in re.finditer(pattern, text):
                name = match.group()
                canonical = canonical_person(name)
                persons[canonical] = {
                    "name": canonical,
                    "raw_name": name,
                    "source": "rule",
                }

        # Known persons by exact name
        for canonical, aliases in KNOWN_PERSONS.items():
            for alias in aliases:
                if alias.lower() in text.lower():
                    persons[canonical] = {
                        "name": canonical,
                        "raw_name": alias,
                        "source": "known_list",
                    }

        # spaCy NER
        if self._nlp:
            doc = self._nlp(text[:100000])  # Truncate for performance
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    name = ent.text.strip()
                    if len(name) < 3:
                        continue
                    canonical = canonical_person(name)
                    if canonical not in persons:
                        persons[canonical] = {
                            "name": canonical,
                            "raw_name": name,
                            "source": "spacy",
                        }

        return list(persons.values())

    def _extract_groups(self, text: str) -> list[dict]:
        """Extract group/organization entities."""
        groups = {}

        for pattern in GROUP_PATTERNS:
            for match in re.finditer(pattern, text):
                name = match.group()
                key = normalize(name)
                groups[key] = {"name": name, "source": "rule"}

        for canonical, aliases in KNOWN_GROUPS.items():
            for alias in aliases:
                if alias.lower() in text.lower():
                    groups[canonical] = {"name": aliases[0], "source": "known_list"}

        # spaCy NER for ORG
        if self._nlp:
            doc = self._nlp(text[:100000])
            for ent in doc.ents:
                if ent.label_ == "ORG":
                    name = ent.text.strip()
                    if len(name) < 3:
                        continue
                    key = normalize(name)
                    if key not in groups:
                        groups[key] = {"name": name, "source": "spacy"}

        return list(groups.values())

    def _extract_places(self, text: str) -> list[dict]:
        """Extract place/location entities."""
        places = {}

        for pattern in PLACE_PATTERNS:
            for match in re.finditer(pattern, text):
                name = match.group()
                key = normalize(name)
                places[key] = {"name": name, "source": "rule"}

        for canonical, aliases in KNOWN_PLACES.items():
            for alias in aliases:
                if alias.lower() in text.lower():
                    places[canonical] = {"name": aliases[0], "source": "known_list"}

        # spaCy NER for GPE/LOC
        if self._nlp:
            doc = self._nlp(text[:100000])
            for ent in doc.ents:
                if ent.label_ in ("GPE", "LOC", "FAC"):
                    name = ent.text.strip()
                    if len(name) < 3:
                        continue
                    key = normalize(name)
                    if key not in places:
                        places[key] = {"name": name, "source": "spacy"}

        return list(places.values())

    def _extract_events(self, text: str) -> list[dict]:
        """Extract events by detecting date anchors + action verbs."""
        events = []
        sentences = split_sentences(text)

        for sent in sentences:
            sent_lower = sent.lower()
            has_trigger = any(trigger in sent_lower for trigger in EVENT_TRIGGERS)
            has_date = extract_date_from_text(sent) is not None

            if has_trigger and has_date:
                date = extract_date_from_text(sent)
                # Try to label the event
                label = sent[:120]
                events.append({
                    "label": label,
                    "event_type": "unknown",
                    "start_date": date,
                    "end_date": None,
                    "description": sent,
                })
            elif has_trigger:
                # Event without a specific date — still capture
                label = sent[:120]
                events.append({
                    "label": label,
                    "event_type": "unknown",
                    "start_date": None,
                    "end_date": None,
                    "description": sent,
                })

        return events

    def _extract_claims(self, text: str) -> list[dict]:
        """Extract claims: sentences containing assertion verbs."""
        claims = []
        sentences = split_sentences(text)

        for sent in sentences:
            sent_lower = sent.lower()
            has_trigger = any(trigger in sent_lower for trigger in CLAIM_TRIGGERS)

            if not has_trigger:
                continue

            # Determine stance
            stance = self._classify_stance(sent)

            # Determine claim type
            claim_type = self._classify_claim_type(sent)

            # Try to identify speaker (heuristic: "X said/claimed/..." or "X, ... said")
            speaker = self._extract_speaker(sent)

            # Identify targets (persons/groups mentioned in the sentence)
            targets = []
            for p in self._extract_persons(sent):
                targets.append({"type": "person", "name": p["name"]})
            for g in self._extract_groups(sent):
                targets.append({"type": "group", "name": g["name"]})

            claims.append({
                "text": sent,
                "claim_type": claim_type,
                "stance": stance,
                "confidence": 0.5,  # Default confidence
                "speaker": speaker,
                "targets": targets,
                "evidence_mode": self._classify_evidence_mode(sent),
            })

        return claims

    def _classify_stance(self, sentence: str) -> str:
        """Classify the stance of a claim."""
        sent_lower = sentence.lower()
        critical_words = ["abuse", "cult", "manipulated", "suffered", "controlled", "omitted", "exaggerated", "denied", "harmful"]
        supportive_words = ["beautiful", "loving", "spiritual", "wonderful", "amazing", "transformative", "healing"]
        self_myth_words = ["i was", "i am", "we were", "i became", "chosen", "divine"]

        if any(w in sent_lower for w in critical_words):
            return "critical"
        if any(w in sent_lower for w in self_myth_words):
            return "self-mythologizing"
        if any(w in sent_lower for w in supportive_words):
            return "supportive"
        return "neutral"

    def _classify_claim_type(self, sentence: str) -> str:
        """Classify the type of a claim."""
        sent_lower = sentence.lower()
        type_keywords = {
            "abuse_allegation": ["abuse", "abused", "suffered", "harmful", "trauma"],
            "financial_control": ["money", "financial", "withheld", "support", "wages", "sold"],
            "sexual_control": ["sexual", "wives", "marriage", "polygamy"],
            "documentary_critique": ["documentary", "film", "omits", "doesn't tell"],
            "historical_dispute": ["military", "judo", "exaggerated", "claimed to be", "actually"],
            "biographical": ["born", "grew up", "moved", "joined", "left", "died", "founded"],
        }

        for ctype, keywords in type_keywords.items():
            if any(kw in sent_lower for kw in keywords):
                return ctype
        return "biographical"

    def _classify_evidence_mode(self, sentence: str) -> str:
        """Classify the evidence mode of a claim."""
        sent_lower = sentence.lower()
        if any(w in sent_lower for w in ["i ", "we ", "my ", "our "]):
            return "first_person"
        if any(w in sent_lower for w in ["tape", "recording", "audio"]):
            return "audio_tape_summary"
        if any(w in sent_lower for w in ["clipping", "archive", "archival", "newspaper"]):
            return "archival_clipping"
        if any(w in sent_lower for w in ["comment", "thread", "replied"]):
            return "commentary"
        return "secondary_report"

    def _extract_speaker(self, sentence: str) -> Optional[str]:
        """Try to identify the speaker of a quoted/paraphrased claim."""
        # Pattern: "X said/claimed/remembered..."
        match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:said|claimed|remembered|described|argued|wrote|stated|recalled|insisted|denied)", sentence)
        if match:
            return match.group(1)

        # Pattern: "According to X, ..."
        match = re.match(r"^According to\s+(.+?),", sentence, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Pattern: "X, ... said/claimed"
        match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),", sentence)
        if match:
            # Check if a claim verb appears later
            rest = sentence[len(match.group(1)):]
            if any(v in rest.lower() for v in CLAIM_TRIGGERS):
                return match.group(1)

        return None
