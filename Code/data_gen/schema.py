"""Record schema, tag vocabulary, value rendering and comparison.

A record has 10 labelled fields. Each filled field holds a small dict (see FIELD_DOCS).
Lists use fixed tags so that a verifier's answer can be compared by code, not by judgment.
"""
from __future__ import annotations

import re

FIELDS = [
    "strength", "dose_amount", "frequency", "food_timing", "duration",
    "administration", "interactions", "warning_signs", "missed_dose", "max_daily",
]
CORE_FIELDS = ["strength", "dose_amount", "frequency", "duration"]
LABELS = ["correct", "partial", "omitted", "changed", "added"]

FIELD_NAMES = {  # how the field is named in prompts
    "strength": "strength", "dose_amount": "how many per dose", "frequency": "how often",
    "food_timing": "food and timing", "duration": "how long", "administration": "how to take it",
    "interactions": "things to avoid or that are fine", "warning_signs": "warning signs and what to do",
    "missed_dose": "missed dose", "max_daily": "maximum per day",
}

FIELD_DOCS = {
    "strength": '{"value": 875, "unit": "mg"}',
    "dose_amount": '{"count": 1, "form": "tablet"}',
    "frequency": '{"per_day": 2} or {"every_hours": 12} or {"every_hours": [4, 6], "as_needed": true}',
    "food_timing": '{"tags": ["start_of_meal"]}',
    "duration": '{"kind": "days", "n": 10, "finish_course": true} | {"kind": "weeks", "n": 4} | '
                '{"kind": "ongoing", "dont_stop_suddenly": true} | {"kind": "as_short_as_possible"} | {"kind": "until_feel_better"}',
    "administration": '{"tags": ["swallow_whole", "do_not_chew_or_crush"]}',
    "interactions": '{"items": [{"agent": "alcohol", "rule": "avoid"}]}',
    "warning_signs": '{"groups": [{"symptoms": ["rash", "swelling"], "action": "call_doctor_now"}]}',
    "missed_dose": '{"tag": "take_when_remembered_skip_if_close", "no_double": true}',
    "max_daily": '{"value": 3200, "unit": "mg"} or {"no_limit": true}',
}

FOOD = {
    "with_food": "with food", "with_meals": "with meals",
    "with_meals_or_milk": "with meals or milk if it upsets your stomach",
    "start_of_meal": "at the start of a meal", "before_meal": "before a meal", "after_meal": "after a meal",
    "empty_stomach": "on an empty stomach", "with_or_without_food": "with or without food",
    "at_bedtime": "at bedtime", "in_the_morning": "in the morning",
    "with_milk": "with a glass of milk", "no_dairy": "not with dairy products",
}
ADMIN = {
    "swallow_whole": "swallow it whole", "do_not_chew_or_crush": "do not chew or crush it",
    "can_chew_or_crush": "it is fine to chew or crush it",
    "may_sprinkle_on_applesauce": "if swallowing is hard, open the capsule and mix the contents with applesauce",
    "full_glass_of_water": "take it with a full glass of water",
    "stay_upright_30_min": "stay upright for 30 minutes after taking it",
    "lie_down_after": "lie down after taking it", "dissolve_in_water": "dissolve it in water first",
}
AGENTS = {
    "alcohol": "alcohol", "antacids": "antacids", "grapefruit": "grapefruit juice", "coffee": "coffee",
    "dairy": "dairy products", "nsaids_or_aspirin": "NSAID painkillers or aspirin", "blood_thinners": "blood thinners",
}
RULES = {
    "avoid": "avoid {a}", "avoid_heavy": "do not drink a lot of {a} or binge drink", "limit": "limit {a}",
    "ok": "it is fine to take {a} with it", "tell_doctor": "tell your doctor before taking {a}",
}
ACTIONS = {
    "emergency_help": "get emergency help right away",
    "stop_and_call_doctor_now": "stop taking it and call your doctor right away",
    "stop_and_report": "stop taking it right away and tell your doctor",
    "call_doctor_now": "call your doctor right away",
    "call_doctor_or_911": "call your doctor right away, or 911 in an emergency",
    "call_doctor_soon": "contact your doctor as soon as possible",
    "wait_and_see": "wait and see if it passes", "take_extra_dose": "take an extra dose",
}
MISSED = {
    "take_when_remembered_skip_if_close": "take it as soon as you remember, but if it is almost time for the next dose, skip the missed one",
    "skip_take_next": "skip the missed dose and take the next one at the usual time",
    "double_next_dose": "take two doses next time to make up for it",
    "take_two_if_missed": "if you miss one, take two together",
}
VOCAB = {"food_timing": FOOD, "administration": ADMIN, "agents": AGENTS, "rules": RULES,
         "actions": ACTIONS, "missed_dose": MISSED}

UNIT_ALIASES = {"milligram": "mg", "milligrams": "mg", "mgs": "mg", "gram": "g", "grams": "g",
                "microgram": "mcg", "micrograms": "mcg", "ml": "mL", "milliliter": "mL", "milliliters": "mL"}


# ---------------------------------------------------------------- rendering

def _num(x):
    return int(x) if float(x).is_integer() else x


def _unit(u: str) -> str:
    u = (u or "").strip()
    return UNIT_ALIASES.get(u.lower(), u)


def render(field: str, v: dict) -> str:
    """Plain English for a field value, used in doctor prompts and patient specs."""
    if v is None:
        return "not specified"
    if "vague" in v:
        return v["vague"]
    if field in ("strength", "max_daily"):
        if v.get("no_limit"):
            return "there is no daily limit"
        s = f"{_num(v['value'])} {_unit(v['unit'])}"
        return s if field == "strength" else f"no more than {s} in 24 hours"
    if field == "dose_amount":
        c, form = _num(v["count"]), v["form"]
        return f"{c} {form}" + ("s" if c != 1 and not form.endswith("s") else "")
    if field == "frequency":
        if "per_day" in v:
            n = v["per_day"]
            return {1: "once a day", 2: "twice a day"}.get(n, f"{n} times a day")
        h = v["every_hours"]
        txt = f"every {h[0]} to {h[1]} hours" if isinstance(h, list) else f"every {h} hours"
        return txt + (" as needed" if v.get("as_needed") else "")
    if field == "food_timing":
        return ", ".join(FOOD[t] for t in v["tags"])
    if field == "administration":
        return "; ".join(ADMIN[t] for t in v["tags"])
    if field == "duration":
        k = v["kind"]
        base = {"days": f"for {v.get('n')} days", "weeks": f"for {v.get('n')} weeks",
                "ongoing": "every day, long term", "as_short_as_possible": "only for as long as you need it",
                "until_feel_better": "until you feel better"}[k]
        if v.get("finish_course"):
            base += ", and finish all of it even if you feel better"
        if v.get("dont_stop_suddenly"):
            base += ", and do not stop suddenly without talking to your doctor"
        return base
    if field == "interactions":
        return "; ".join(RULES[i["rule"]].format(a=AGENTS[i["agent"]]) for i in v["items"])
    if field == "warning_signs":
        parts = []
        for g in v["groups"]:
            s = ", ".join(g["symptoms"])
            parts.append(f"if you get {s}: {ACTIONS[g['action']]}" if g.get("action") else f"watch for {s}")
        return "; ".join(parts)
    if field == "missed_dose":
        s = MISSED[v["tag"]]
        return s + ("; never take two doses at once" if v.get("no_double") else "")
    raise KeyError(field)


# ---------------------------------------------------------------- comparison

def _freq_key(v: dict, tid_equals_q8h: bool):
    if "per_day" in v:
        return ("per_day", float(v["per_day"]), bool(v.get("as_needed")))
    h = v["every_hours"]
    if isinstance(h, list):
        return ("range", tuple(h), bool(v.get("as_needed")))
    if 24 % h == 0 and (tid_equals_q8h or h != 8):
        return ("per_day", 24 / h, bool(v.get("as_needed")))
    return ("every_hours", float(h), bool(v.get("as_needed")))


def _words(s: str) -> set:
    stop = {"a", "an", "the", "of", "or", "and", "your", "in", "on", "to", "you", "any", "other", "very"}
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in stop}


def symptom_match(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def same_value(field: str, a: dict, b: dict, tid_equals_q8h: bool = True) -> bool:
    """True when two stated values mean the same thing (equivalence table)."""
    if a is None or b is None:
        return a is b
    if field in ("strength", "max_daily"):
        if a.get("no_limit") or b.get("no_limit"):
            return bool(a.get("no_limit")) == bool(b.get("no_limit"))
        return float(a["value"]) == float(b["value"]) and _unit(a["unit"]).lower() == _unit(b["unit"]).lower()
    if field == "dose_amount":
        return float(a["count"]) == float(b["count"])  # form wording ("pill" vs "tablet") does not matter
    if field == "frequency":
        return _freq_key(a, tid_equals_q8h) == _freq_key(b, tid_equals_q8h)
    if field in ("food_timing", "administration"):
        return set(a["tags"]) == set(b["tags"])
    if field == "duration":
        def key(v):
            k, n = v["kind"], v.get("n")
            if k == "weeks":
                k, n = "days", n * 7
            return (k, n, bool(v.get("finish_course")), bool(v.get("dont_stop_suddenly")))
        return key(a) == key(b)
    if field == "interactions":
        return {(i["agent"], i["rule"]) for i in a["items"]} == {(i["agent"], i["rule"]) for i in b["items"]}
    if field == "warning_signs":
        return _ws_relation(a, b) == "same"
    if field == "missed_dose":
        return a["tag"] == b["tag"] and bool(a.get("no_double")) == bool(b.get("no_double"))
    raise KeyError(field)


def _ws_relation(said: dict, ref: dict) -> str:
    """'same', 'subset' (some symptoms or no action), or 'different' for warning-sign groups."""
    ref_syms = [(s, g.get("action")) for g in ref["groups"] for s in g["symptoms"]]
    said_syms = [(s, g.get("action")) for g in said["groups"] for s in g["symptoms"]]
    matched, missing_action = 0, False
    for s, act in said_syms:
        hit = next(((rs, ra) for rs, ra in ref_syms if symptom_match(s, rs)), None)
        if hit is None:
            return "different"
        if act is None:
            missing_action = True
        elif act != hit[1]:
            return "different"
        matched += 1
    covered = {rs for rs, _ in ref_syms if any(symptom_match(s, rs) for s, _ in said_syms)}
    if len(covered) == len(ref_syms) and not missing_action:
        return "same"
    return "subset" if matched else "different"


def is_subset(field: str, said: dict, ref: dict) -> bool:
    """True when `said` gives part of a list field's content and nothing wrong."""
    if field in ("food_timing", "administration"):
        return set(said["tags"]) < set(ref["tags"])
    if field == "interactions":
        s = {(i["agent"], i["rule"]) for i in said["items"]}
        return 0 < len(s) and s < {(i["agent"], i["rule"]) for i in ref["items"]}
    if field == "warning_signs":
        return _ws_relation(said, ref) == "subset"
    if field == "duration":  # the days without "finish the course"
        return said["kind"] == ref["kind"] and said.get("n") == ref.get("n") and \
            ref.get("finish_course") and not said.get("finish_course")
    if field == "missed_dose":
        return said["tag"] == ref["tag"] and ref.get("no_double") and not said.get("no_double")
    return False
