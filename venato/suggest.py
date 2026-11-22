"""
What to track for a goal, from the words in it (setup's "What would you track?"). A keyword map:
no AI, no network, nothing saved here. Each suggestion is an example to pick from, never a default.

    for_goal("Run a 10k") -> [{"kind": "category", "name": "Exercise", "cid": "exercise"},
                              {"kind": "habit", "name": "Trained"}]

Kinds: "habit" (a habit to tick), "category" (a timetable category; cid is its EXAMPLE_CATEGORIES id),
"sleep" and "water" (the Daily Log switches). Blocks are never suggested.
"""

import re

# (words that trigger it, what it suggests). Words match whole, with their endings taken off:
# "running" and "runners" find "run", "prune" finds nothing. Order is the order suggestions come back in.
RULES = [
    (("run", "jog", "marathon", "5k", "10k", "gym", "lift", "weights", "fitness", "exercise", "workout", "swim",
      "cycle", "strength", "football", "hike"),
     [("category", "Exercise", "exercise"), ("habit", "Trained", None)]),
    (("exam", "degree", "first", "2:1", "2:2", "grade", "revise", "revision", "study", "essay", "dissertation",
      "thesis", "gpa", "pass", "term", "module", "uni"),
     [("category", "Study", "study")]),
    (("read", "book", "novel"),
     [("category", "Reading", "reading"), ("habit", "Read", None)]),
    (("tired", "sleep", "insomnia", "rest", "exhausted"),
     [("sleep", "Track my sleep", None)]),
    (("water", "hydrate", "hydration", "drink"),
     [("water", "Track my water", None)]),
    (("meditate", "meditation", "mindful", "mindfulness", "calm", "stress", "anxiety"),
     [("habit", "Meditate", None)]),
    (("code", "program", "programming", "project", "build", "portfolio"),
     [("category", "Projects", "projects")]),
    (("cook", "eat", "diet", "meal"),
     [("category", "Meals", "meals"), ("habit", "Cooked at home", None)]),
    (("write", "journal", "blog"),
     [("habit", "Write", None)]),
]


def _forms(word):
    """The word and what is left with an ending off: running -> run, writing -> write, books -> book."""
    out = {word}
    for end in ("ing", "ed", "er", "ers", "es", "s"):
        stem = word[:-len(end)]
        if word.endswith(end) and len(stem) >= 3:
            out |= {stem, stem + "e"}
            if stem[-1] == stem[-2]:
                out.add(stem[:-1])
    return out


def for_goal(text):
    """The suggestions for one goal's text, without repeats: [{"kind", "name", "cid"?}]."""
    forms = set()
    for word in re.findall(r"[a-z0-9:]+", str(text or "").lower()):
        forms |= _forms(word)
    out, seen = [], set()
    for triggers, items in RULES:
        if not forms.intersection(triggers):
            continue
        for kind, name, cid in items:
            if (kind, name) not in seen:
                seen.add((kind, name))
                out.append({"kind": kind, "name": name, **({"cid": cid} if cid else {})})
    return out
