#!/usr/bin/env python3
"""Generate per-host outreach email drafts for graph persons.

Queries data/graph.db for CO_APPEARANCE events per person, normalizes
venue/location strings to canonical host organizations, and writes one
markdown email draft per host under docs/outreach/<person>/.

Usage:
    python scripts/52_generate_outreach_emails.py            # write files
    python scripts/52_generate_outreach_emails.py --dry-run  # print plan only
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path("data/graph.db")
OUT = Path("docs/outreach")

SIGN = """Everything collected is being preserved as source material for an accurate
public record of the teaching career. I am happy to share the compiled history
with your organization when complete, and to credit you as a source.

Thank you for keeping these records — school archives like yours are often the
only place this history survives.

Warm regards,
Ken Kron
Story Graph project — martial arts history documentation
"""

ASKS = """I'd be very grateful for anything you can share from your archives:

- Confirmation of the date(s) and the seminar title/theme
- Flyers, announcements, programs, or photos from the event (scans or photos of originals are fine)
- The rank held at the time, if recorded
- Names of any co-instructors or organizers involved
- Any earlier or later visits we may not have on record
"""


def slugify(s):
    s = re.sub(r"[—–/()&.,'\"]", " ", s.lower())
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", s)).strip("-")


def canon_rules(rules, strict=False):
    compiled = [(re.compile(p, re.I), name) for p, name in rules]

    def canon(text):
        t = (text or "").strip()
        for pat, name in compiled:
            if pat.search(t):
                return name
        return None if strict else (t or None)

    return canon


# ---------------------------------------------------------------- Moon
MOON_RULES = canon_rules([
    (r"dance palace", "Dance Palace — Point Reyes Station, CA"),
    (r"aikido of marin", "Aikido of Marin — Fairfax, CA"),
    (r"fairfax community church", "Fairfax Community Church — Fairfax, CA"),
    (r"mountain wind", "Mountain Wind Aikido — Santa Rosa, CA"),
    (r"north coast|northcoast", "North Coast Aikido — Arcata, CA"),
    (r"city aikido", "City Aikido — San Francisco, CA"),
    (r"maastricht", "Aikido Maastricht — Netherlands"),
    (r"awase|helsinki", "Awase — Helsinki, Finland"),
    (r"riviera|lake geneva|novum|montreux|vevey", "Riviera Seminar / Novum Experience — Lake Geneva, Switzerland"),
    (r"riai|auckland|new zealand|nz-tour|down under", "Riai Aikido — New Zealand"),
], strict=True)
MOON_EXCLUDE = re.compile(r"durham|performance edge|imtd|lake trails|bosnia|cyprus|interview|podcast|herald-sun|conference", re.I)
MOON_INTRO = (
    "I'm researching and documenting the aikido teaching career of Richard Moon "
    "Sensei (6th dan, Aikido of Marin / City Aikido of San Francisco) for a "
    "biographical project — including a sourced historical record of his "
    "seminars and guest teaching over the past five decades.\n\n"
    "Our records show Richard Moon taught at your organization:"
)
MOON_SUBJECT = "Documenting Richard Moon Sensei's teaching history — request for your records"

# ---------------------------------------------------------------- Ikeda
IKEDA_RULES = canon_rules([
    (r"oberlin", "Oberlin Aikikai — Oberlin College, OH"),
    (r"river of life|seishinkan", "Aikido Seishinkan — River of Life Center, PA"),
    (r"boulder aikikai|summer camp in the rockies|aiki summit", "Boulder Aikikai — Boulder, CO"),
    (r"shindai|boys.?girls club", "Shindai Aikikai — Orlando, FL"),
    (r"jiai", "Jiai Aikido — San Diego, CA"),
    (r"bond st|new york aikido society", "Bond Street Dojo / New York Aikido Society — NY"),
    (r"catholic univ|aikido shobukan|asu (summer|winter)", "Aikido Shobukan Dojo / ASU — Washington, DC"),
    (r"milwaukee", "Milwaukee Aikido Club / Shobukan — WI"),
    (r"pines|fall mountain camp|arizona aikido", "Arizona Aikido Fall Mountain Camp — Emmanuel Pines, AZ"),
    (r"butokuden|kyoto budo", "Kyoto Butokuden — Japan"),
    (r"livermore|shinrei", "Aikido of Livermore — Shinrei Dojo, CA"),
    (r"vriesman", "Vriesman Dojo — Netherlands"),
    (r"amsterdam|dutch aikikai", "Dutch Aikikai Foundation — Amsterdam, Netherlands"),
    (r"chishin|grace academy", "Chishin Dojo — Coventry, England"),
    (r"tamalpais", "Aikido of Tamalpais — Mill Valley, CA"),
    (r"cruise", "The Aikido Cruise"),
    (r"denver buddhist|tri.?state", "Denver Buddhist Temple — CO"),
    (r"kenkyukai|aki santa barbara", "Aikido Kenkyukai Santa Barbara (AKI) — CA"),
    (r"shobu aikido.*boston", "Shobu Aikido of Boston — MA"),
    (r"shobu aikido houston", "Shobu Aikido Houston — TX"),
    (r"shobu aikido of maine|aikido of maine", "Shobu Aikido of Maine — ME"),
    (r"aikido schools of n", "Aikido Schools of New Jersey — NJ"),
    (r"central ohio", "Aikido School of Central Ohio — OH"),
    (r"louisville", "Louisville Aikikai — KY"),
    (r"agatsu", "Aikikai Agatsu — Finland"),
    (r"abiding spirit", "Abiding Spirit Aikikai — Crystal Lake, IL"),
    (r"bridge seminar", "Aikido Bridge Philadelphia — PA"),
    (r"kirmayer|aikijuku", "Aikijuku Dojo — Kirmayer Fitness Center, KS"),
    (r"menlo college", "Menlo College — Atherton, CA"),
    (r"youngstown", "Youngstown Cultural Arts Center — Seattle, WA"),
    (r"san rafael embassy", "San Rafael Embassy Suites — CA"),
    (r"hal+e des sports", "Halle des Sports — France"),
    (r"le vigan", "Le Vigan — France"),
    (r"estadio|apada|lisboa", "APADA — Estadio Universitario de Lisboa, Portugal"),
    (r"terakki", "Terakki Vakfi Schools — Istanbul, Turkey"),
    (r"senkai|moscow", "Moscow Aikido Club Senkai — Russia"),
    (r"concordia", "Concordia University — WI"),
    (r"indiana university", "Indiana University Aikido Club — IN"),
    (r"university of chicago", "University of Chicago Aikido Club — IL"),
    (r"dominican college", "Dominican College — San Rafael, CA"),
    (r"philadelphia university", "Philadelphia University — PA"),
    (r"bozeman|big sky", "Big Sky Aikikai — Bozeman, MT"),
    (r"pacific northwest autumn", "Pacific Northwest Autumn Camp — WA"),
    (r"halaw?ai|kona", "Aiki Kai O Kona — Hale Halawai, HI"),
    (r"guad(a|e)loupe", "Aikido of Guadeloupe"),
    (r"martinique", "Aikido of Martinique"),
    (r"kumamoto", "Kumamoto City Budo Center — Japan"),
    (r"nashville|joe c\. davis|ymca", "Nashville Aikikai — TN"),
    (r"shinboku|shimboku", "Aikido Shimboku Dojo — IL"),
    (r"inaka", "Inaka Dojo — IL"),
    (r"fudoshin", "Fudoshin Dojo — CA"),
    (r"musubi", "Musubi Dojo — CA"),
])
IKEDA_EXCLUDE = re.compile(r"pending location|^\s*$", re.I)
IKEDA_INTRO = (
    "I'm researching and documenting the aikido teaching career of Hiroshi Ikeda "
    "Shihan (8th dan, Boulder Aikikai) for a biographical project — including a "
    "sourced historical record of his seminars and guest teaching since the "
    "1970s.\n\n"
    "Our records show Ikeda Shihan taught at your organization:"
)
IKEDA_SUBJECT = "Documenting Hiroshi Ikeda Shihan's teaching history — request for your records"

# ---------------------------------------------------------------- Ralston
RALSTON_SCHOOLS = [
    ("Cheng Hsin headquarters — Oakland, CA",
     "the original Cheng Hsin School of Internal Martial Arts and Center for "
     "Ontological Research (opened Oakland, 1977) and the later Cheng Hsin Center"),
    ("Cheng Hsin Australia", "the Cheng Hsin Australia branch"),
    ("Cheng Hsin Germany / Koeln", "the Cheng Hsin branch in Germany (Koeln)"),
    ("Cheng Hsin Grenoble — France", "the Cheng Hsin branch in Grenoble, France"),
    ("Cheng Hsin Mulhouse — France", "the Cheng Hsin branch in Mulhouse, France"),
    ("Cheng Hsin Hungary", "the Cheng Hsin branch in Hungary"),
    ("Cheng Hsin Netherlands", "the Cheng Hsin branch in the Netherlands"),
    ("Cheng Hsin South Korea", "the Cheng Hsin branch in South Korea"),
    ("Cheng Hsin Swansea — Wales", "the Cheng Hsin branch in Swansea, Wales"),
    ("Cheng Hsin Sweden", "the Cheng Hsin branch in Sweden"),
]
RALSTON_INTRO = (
    "I'm researching and documenting the teaching career of Peter Ralston — "
    "founder of Cheng Hsin, the first non-Asian to win the full-contact World "
    "Championship martial arts tournament (Republic of China, 1978), and author "
    "of The Book of Not Knowing and Zen Body-Being — for a biographical project, "
    "including a sourced record of his workshops, intensives and teaching visits.\n\n"
    "Our records connect your organization to that history as {detail}."
)
RALSTON_SUBJECT = "Documenting Peter Ralston's teaching history — request for your records"


def get_events(cur, person_ids):
    q = """SELECT n.id, n.label, n.metadata_json,
           (SELECT GROUP_CONCAT(d.label, '; ') FROM edges le
            JOIN nodes d ON d.id = le.dst_id
            WHERE le.src_id = n.id AND le.rel_type = 'LOCATED_IN') AS locations
           FROM edges e JOIN nodes n ON n.id = e.dst_id
           WHERE e.rel_type = 'CO_APPEARANCE' AND e.src_id IN (%s)
           GROUP BY n.id""" % ",".join("?" * len(person_ids))
    return cur.execute(q, person_ids).fetchall()


def event_line(label, meta):
    date = meta.get("dates") or meta.get("start_date") or "date unknown"
    return f'- "{label}" — {date}'


def write_email(directory, host, subject, intro, body_lines, dry):
    path = directory / f"{slugify(host)}.md"
    text = (
        f"# Outreach draft — {host}\n\n"
        f"**To:** (contact address TBD — via {host.split(' — ')[0]} website)\n"
        f"**Subject:** {subject}\n\n---\n\n"
        f"Dear {host.split(' — ')[0]} team,\n\n"
        f"My name is Ken Kron. {intro}\n\n"
        + "\n".join(body_lines) + "\n\n" + ASKS + "\n" + SIGN + "\n"
        "_Draft — do not send without review. Generated by scripts/52_generate_outreach_emails.py._\n"
    )
    if dry:
        print(f"  would write {path}")
    else:
        path.write_text(text)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cur = sqlite3.connect(DB).cursor()
    counts = {}

    # --- Moon ---
    d = OUT / "moon"; d.mkdir(parents=True, exist_ok=True)
    hosts = {}
    for _id, label, meta_j, locs in get_events(cur, ["person:richard-moon-aikido", "person-richard-moon"]):
        meta = json.loads(meta_j or "{}")
        blob = " ".join([label, meta.get("venue", ""), locs or "", meta.get("description", "")])
        if MOON_EXCLUDE.search(blob):
            continue
        host = MOON_RULES(blob)
        if host:
            hosts.setdefault(host, []).append(event_line(label, meta))
    # City Aikido — no seminar events in graph, but co-founded by Moon
    hosts.setdefault("City Aikido — San Francisco, CA",
                     ["- Co-founded by Richard Moon; senior instructor — requesting founding date and early history"])
    for host in sorted(hosts):
        write_email(d, host, MOON_SUBJECT, MOON_INTRO, sorted(set(hosts[host])), a.dry_run)
    counts["moon"] = len(hosts)

    # --- Ikeda ---
    d = OUT / "ikeda"; d.mkdir(parents=True, exist_ok=True)
    hosts = {}
    for _id, label, meta_j, locs in get_events(cur, ["person:hiroshi-ikeda"]):
        meta = json.loads(meta_j or "{}")
        venue = meta.get("venue", "")
        blob = " ".join([venue, locs or ""])
        if IKEDA_EXCLUDE.search(blob):
            continue
        host = IKEDA_RULES(blob)
        if host:
            hosts.setdefault(host, []).append(event_line(label, meta))
    for host in sorted(hosts):
        write_email(d, host, IKEDA_SUBJECT, IKEDA_INTRO, sorted(set(hosts[host])), a.dry_run)
    counts["ikeda"] = len(hosts)

    # --- Ralston ---
    d = OUT / "ralston"; d.mkdir(parents=True, exist_ok=True)
    for name, detail in RALSTON_SCHOOLS:
        write_email(d, name, RALSTON_SUBJECT, RALSTON_INTRO.format(detail=detail),
                    ["- Workshops / intensives / teaching visits by Peter Ralston at your school — dates and details requested"], a.dry_run)
    counts["ralston"] = len(RALSTON_SCHOOLS)

    # --- index ---
    if not a.dry_run:
        idx = OUT / "README.md"
        idx.write_text(
            "# Dojo outreach email drafts\n\n"
            "Per-host email drafts requesting archival records (dates, flyers,\n"
            "photos, co-instructors) for documented teaching visits. One file\n"
            "per host organization. **Drafts — review before sending.**\n\n"
            f"- `moon/` — {counts['moon']} hosts of Richard Moon seminars/events\n"
            f"- `ikeda/` — {counts['ikeda']} hosts of Hiroshi Ikeda seminars/events\n"
            f"- `ralston/` — {counts['ralston']} Cheng Hsin schools/branches (Peter Ralston)\n\n"
            "Regenerate: `python scripts/52_generate_outreach_emails.py`\n"
            "(`--dry-run` lists planned files without writing).\n\n"
            "Excluded on purpose: non-dojo hosts (conferences, corporate programs,\n"
            "peace-work organizations) and the Moon events at Performance Edge /\n"
            "IMTD Lake Trails.\n"
        )
    print(f"counts: {counts}")


if __name__ == "__main__":
    sys.exit(main())
