"""
Quick commands: short, everyday logging handled straight away, without asking Claude.

"drank 500ml", "2 glasses of water", "tick gym", "did gym yesterday", "mood 4",
"slept 7.5h", "done finish essay". Each one calls the same tools.py action Claude
would, so the rules are the same (Confirm before overwriting, Undo, and so on).

Anything that isn't a clear match goes to Claude instead: handle() returns None. It
never guesses: a habit or to-do has to match exactly one by name, or the message goes
on to Claude.
"""

import re
from dataclasses import dataclass, field
from datetime import timedelta

from venato import regional
from venato import store
from venato import tools

MARK = "⚡ "                 # shown before a quick reply, so you can tell Claude wasn't asked
GLASS = 0.25                # litres in a glass of water
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
EXTRA = []                  # more commands: functions (text, day) -> tools.Result or None (the private copy adds one)


@dataclass
class Reply:
    reply: str = ""
    pending: list = field(default_factory=list)
    changed: bool = False
    error: str | None = None


def enabled():
    return store.load_settings().get("quick_commands", True)


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower()).rstrip(".!")


def _when(text):
    """Strip a trailing 'today' / 'yesterday' / 'last night'; returns (text, day)."""
    today = store.local_today()
    m = re.search(r"\s+(today|yesterday|last night|this morning)$", text)
    if not m:
        return text, today
    return text[:m.start()], today - timedelta(days=1) if m.group(1) == "yesterday" else today


# --- Water ---

def _water(text, day):
    """'drank 500ml', 'had another 2 glasses of water', 'drank 1.5l in total', '16 oz water'."""
    total = bool(re.search(r"\b(in total|total)\b", text))
    said_water = "water" in text
    text = re.sub(r"\b(in total|total|of water|water)\b", " ", text).strip()
    m = re.fullmatch(r"(?:i\s+)?(?:drank|had|drunk|drink)?\s*(?:another|more|an extra)?\s*"
                     r"(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six)\s*"
                     r"(ml|millilitres?|l|litres?|liters?|oz|fl oz|ounces?|glass(?:es)?|bottles? of \d+ ?ml)?"
                     r"(?:\s+more)?", text)
    if not m or not (m.group(2) or said_water):
        return None                          # a bare number ("had 3") could be anything
    if m.group(1) in WORDS and not (m.group(2) or "").startswith("glass"):
        return None                          # "had a coffee", "drank a lot"
    n = WORDS.get(m.group(1)) or float(m.group(1))
    unit = m.group(2) or ""
    if unit.startswith("glass"):
        litres = n * GLASS
    elif unit.startswith(("ml", "milli")):
        litres = n / 1000
    elif unit.startswith(("oz", "fl", "ounce")):
        litres = n * regional.FL_OZ
    elif unit.startswith(("l", "lit")):
        litres = n
    else:                                    # no unit: the user's own (litres, or ml if it's big)
        litres = regional.water_in(n) if regional.water_unit() != "litres" else (n / 1000 if n > 20 else n)
    if not 0 < litres <= 10:
        return None
    before = store.get_entry(day.isoformat()).get("water") or 0
    new = round(litres if total else before + litres, 3)
    result = tools.log_day(day.isoformat(), water=new)
    if result.changed:
        result.text = f"Water: {regional.water_text(new)} {'today' if day == store.local_today() else 'on ' + tools.nice_day(day.isoformat())}."
    return result


# --- Mood, energy, sleep ---

def _scores(text, day):
    m = re.fullmatch(r"(?:my\s+)?(mood|energy)(?:\s+(?:is|was|=|:))?\s*:?\s*([1-5])(?:\s*/\s*5| out of 5)?", text)
    if m:
        return tools.log_day(day.isoformat(), **{m.group(1): int(m.group(2))})
    m = re.fullmatch(r"(?:i\s+)?(?:slept|sleep(?:\s+(?:was|=|:))?)\s*(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)?", text)
    if m and 0 < float(m.group(1)) <= 16:
        return tools.log_day(day.isoformat(), sleep=float(m.group(1)))
    return None


# --- Habits and to-dos ---

def _tick(text, day):
    """'tick gym', 'did gym', 'done finish essay', 'completed reading'."""
    m = re.fullmatch(r"(?:tick(?:ed)?(?:\s+off)?|did|done(?:\s+with)?|finished|completed?)\s+(?:my\s+|the\s+)?(.+)", text)
    if not m:
        return None
    name = m.group(1).strip()
    habits = [(hid, h) for hid, h in store.get_habits()
              if h.lower() == name or h.lower() == name.rstrip("s") or h.lower().rstrip("s") == name]
    if len(habits) == 1:
        return tools.set_habit(day.isoformat(), habits[0][1], True)
    if habits:
        return None
    if day != store.local_today():
        return None                          # to-dos live in periods: leave dated ones to Claude
    try:
        todo = tools._find_todo(name)
    except tools.ToolError:
        return None
    if todo["title"].lower() != name and name not in todo["title"].lower():
        return None                          # a loose word match: let Claude decide
    return tools.complete_todo(todo["id"])


HANDLERS = [_water, _scores, _tick]


def handle(text):
    """A quick command's reply, or None if Claude should answer this one."""
    if not enabled():
        return None
    text, day = _when(_clean(text))
    if not text or len(text) > 60:
        return None
    from venato import blocks
    for handler in HANDLERS + EXTRA + [q for b in blocks.enabled() for q in b.quick]:
        try:
            result = handler(text, day)
        except tools.ToolError:
            return None                      # e.g. an odd value: Claude can explain it better
        except Exception:                    # a bug in a block's handler must never break the chat box
            return None
        if result is None:
            continue
        reply = Reply(changed=result.changed)
        if result.pending:
            reply.pending.append(result.pending)
            reply.reply = MARK + f"{result.pending.summary}: confirm below."
        else:
            reply.reply = MARK + result.text
        return reply
    return None
