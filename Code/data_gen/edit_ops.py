"""Edit operators and patient specs.

A spec says, for every field, what the patient will say: keep the record's value, delete it,
change it, blur it, or add a rule the record does not have. Labels are read off the spec.
"""
from __future__ import annotations

import copy
import random

from .schema import FIELDS, FIELD_NAMES, render

OP_TO_LABEL = {"keep": "correct", "delete": "omitted", "change": "changed", "blur": "partial", "add": "added"}

# ---------------------------------------------------------------- change operators

FOOD_SWAP = {"with_food": "empty_stomach", "with_meals": "empty_stomach", "start_of_meal": "empty_stomach",
             "with_meals_or_milk": "empty_stomach", "before_meal": "after_meal", "after_meal": "before_meal",
             "empty_stomach": "with_food", "with_or_without_food": "empty_stomach",
             "at_bedtime": "in_the_morning", "in_the_morning": "at_bedtime"}
ADMIN_SWAP = {"swallow_whole": "can_chew_or_crush", "do_not_chew_or_crush": "can_chew_or_crush",
              "stay_upright_30_min": "lie_down_after"}
RULE_FLIP = {"avoid": "ok", "avoid_heavy": "ok", "limit": "ok", "ok": "avoid", "tell_doctor": "ok"}


def change(field: str, v: dict, card: dict, rng: random.Random):
    """Return (new_value, operator_name) or None when no realistic change exists."""
    v = copy.deepcopy(v)
    if field == "strength":
        others = [p["strength"]["value"] for p in card.get("products", []) if p["strength"]["value"] != v["value"]]
        opts = [("x10", v["value"] * 10), ("other_strength", rng.choice(others) if others else None)]
        if v["value"] % 10 == 0:
            opts.append(("div10", v["value"] // 10))
        name, val = rng.choice([o for o in opts if o[1] is not None])
        return {"value": val, "unit": v["unit"]}, name
    if field == "dose_amount":
        c = v["count"]
        new = rng.choice([c + 1, c * 2] + ([c - 1] if c > 1 else []))
        return {"count": new, "form": v["form"]}, "count"
    if field == "frequency":
        if v.get("as_needed"):
            h = v["every_hours"]
            lo = h[0] if isinstance(h, list) else h
            return {"every_hours": lo}, "as_needed_to_regular"
        if "per_day" in v:
            n = v["per_day"]
            return {"per_day": rng.choice([x for x in (n - 1, n + 1) if x >= 1])}, "times_per_day"
        h = v["every_hours"]
        return {"every_hours": rng.choice([x for x in (4, 6, 8, 12, 24) if x != h])}, "interval"
    if field == "food_timing":
        swappable = [t for t in v["tags"] if t in FOOD_SWAP]
        if not swappable:
            return None
        t = rng.choice(swappable)
        v["tags"] = [FOOD_SWAP[t] if x == t else x for x in v["tags"]]
        return v, "food_swap"
    if field == "duration":
        k = v["kind"]
        if k in ("days", "weeks"):
            if v.get("finish_course") and rng.random() < 0.6:
                return {"kind": "until_feel_better"}, "until_feel_better"
            n = v["n"]
            return dict(v, n=max(1, n // 2 if n > 3 else n - 1)), "shorter"
        if k == "ongoing":
            return {"kind": "days", "n": rng.choice([5, 7, 14])}, "ongoing_to_fixed"
        if k == "as_short_as_possible":
            return {"kind": "ongoing"}, "short_to_ongoing"
        return None
    if field == "administration":
        swappable = [t for t in v["tags"] if t in ADMIN_SWAP]
        if not swappable:
            return None
        t = rng.choice(swappable)
        new = ADMIN_SWAP[t]
        v["tags"] = sorted({new if x == t else x for x in v["tags"] if not (x in ADMIN_SWAP and ADMIN_SWAP[x] == new and x != t)})
        return v, "admin_negate"
    if field == "interactions":
        i = rng.randrange(len(v["items"]))
        v["items"][i]["rule"] = RULE_FLIP[v["items"][i]["rule"]]
        return v, "rule_flip"
    if field == "warning_signs":
        g = rng.randrange(len(v["groups"]))
        v["groups"][g]["action"] = rng.choice(["wait_and_see", "take_extra_dose"])
        return v, "wrong_action"
    if field == "missed_dose":
        return {"tag": "double_next_dose", "no_double": False}, "double_up"
    if field == "max_daily":
        if rng.random() < 0.5:
            return {"no_limit": True}, "no_limit"
        return {"value": v["value"] * 2, "unit": v["unit"]}, "double_limit"
    raise KeyError(field)


# ---------------------------------------------------------------- blur operators

def blur(field: str, v: dict, card: dict, rng: random.Random):
    """Return (vague_or_subset_value, operator_name) or None."""
    v = copy.deepcopy(v)
    if field == "strength":
        return {"vague": rng.choice(["the strong one", "the regular strength", "whatever strength they gave me"])}, "vague"
    if field == "dose_amount":
        return {"vague": rng.choice(["a pill or two", "a couple", "some"])}, "vague"
    if field == "frequency":
        if v.get("as_needed"):
            return {"vague": "whenever I need it"}, "drop_interval"
        if v.get("per_day") == 1:
            return {"vague": "regularly"}, "vague"
        return {"vague": rng.choice(["more than once a day", "every few hours", "a few times a day"])}, "vague"
    if field in ("food_timing", "administration"):
        if len(v["tags"]) >= 2:
            v["tags"] = rng.sample(v["tags"], len(v["tags"]) - 1)
            return v, "subset"
        if field == "food_timing" and v["tags"][0] in ("with_food", "with_meals", "start_of_meal", "before_meal", "after_meal"):
            return {"vague": "around mealtimes"}, "vague"
        return None
    if field == "duration":
        if v.get("finish_course"):
            v.pop("finish_course")
            return v, "drop_finish_course"
        if v["kind"] in ("days", "weeks"):
            return {"vague": rng.choice(["for a while", "for some time"])}, "vague"
        return None
    if field == "interactions":
        if len(v["items"]) >= 2:
            v["items"] = rng.sample(v["items"], len(v["items"]) - 1)
            return v, "subset"
        return {"vague": f"be careful with {v['items'][0]['agent'].replace('_', ' ')}"}, "vague"
    if field == "warning_signs":
        syms = [(gi, s) for gi, g in enumerate(v["groups"]) for s in g["symptoms"]]
        if len(syms) >= 2 and rng.random() < 0.6:
            keep = set(rng.sample(syms, max(1, len(syms) // 2)))
            groups = []
            for gi, g in enumerate(v["groups"]):
                s = [x for x in g["symptoms"] if (gi, x) in keep]
                if s:
                    groups.append({"symptoms": s, "action": g["action"]})
            return {"groups": groups}, "some_symptoms"
        for g in v["groups"]:
            g["action"] = None
        return v, "no_action"
    if field == "missed_dose":
        if v.get("no_double"):
            v["no_double"] = False
            return v, "drop_no_double"
        return None
    if field == "max_daily":
        return {"vague": "don't take too many"}, "vague"
    raise KeyError(field)


# ---------------------------------------------------------------- add operators (empty fields)

def add(field: str, record: dict, card: dict, rng: random.Random):
    if field == "food_timing":
        return {"tags": [rng.choice(["with_milk", "no_dairy", "at_bedtime", "empty_stomach"])]}, "add_food"
    if field == "administration":
        return {"tags": [rng.choice(["dissolve_in_water", "can_chew_or_crush", "full_glass_of_water"])]}, "add_admin"
    if field == "interactions":
        return {"items": [{"agent": rng.choice(["coffee", "dairy", "grapefruit", "alcohol"]), "rule": "avoid"}]}, "add_avoid"
    if field == "warning_signs":
        return {"groups": [{"symptoms": [rng.choice(["dizziness", "a headache", "feeling sleepy"])],
                            "action": rng.choice(["call_doctor_now", "stop_and_call_doctor_now"])}]}, "add_warning"
    if field == "missed_dose":
        return {"tag": rng.choice(["take_two_if_missed", "skip_take_next"]), "no_double": False}, "add_missed"
    if field == "max_daily":
        s = record["fields"]["strength"]
        return {"value": s["value"] * rng.choice([2, 3, 4]), "unit": s["unit"]}, "add_limit"
    return None


# ---------------------------------------------------------------- specs

STYLE_SPACE = {
    "speaker": ["patient", "patient", "caregiver"],
    "literacy": ["low", "medium", "high"],
    "english": ["native", "native", "non-native"],
    "register": ["casual", "neutral"],
    "length": ["short", "medium", "long"],
    "confidence": ["sure", "sure", "hedging"],
    "channel": ["spoken", "typed"],
}
LENGTH_WORDS = {"short": "15-40 words", "medium": "40-80 words", "long": "80-150 words, rambling"}
NUMERIC_FIELDS = {"strength", "dose_amount", "frequency", "max_daily"}


def _pick_op(rng, probs):
    ops, w = zip(*probs.items())
    return rng.choices(ops, weights=w)[0]


def sample_styles(n: int, rng: random.Random) -> list[dict]:
    """Stratify length and literacy across a record's n versions; sample the rest."""
    lengths = (STYLE_SPACE["length"] * n)[:n]
    literacy = (STYLE_SPACE["literacy"] * n)[:n]
    rng.shuffle(lengths)
    rng.shuffle(literacy)
    out = []
    for i in range(n):
        s = {k: rng.choice(vals) for k, vals in STYLE_SPACE.items()}
        s["length"], s["literacy"] = lengths[i], literacy[i]
        out.append(s)
    return out


def sample_spec(record: dict, card: dict, cfg: dict, rng: random.Random, version: int, style: dict) -> dict:
    ocfg, ncfg = cfg["ops"], cfg["noise"]
    fields = record["fields"]
    filled = [f for f in FIELDS if fields.get(f) is not None]
    empty = [f for f in FIELDS if fields.get(f) is None]
    ops: dict[str, dict] = {}
    fully_correct = rng.random() < ocfg["fully_correct_share"]

    for f in filled:
        if fully_correct:
            ops[f] = {"op": "keep", "value": fields[f]}
            continue
        probs = dict(ocfg["filled"])
        while True:
            op = _pick_op(rng, probs)
            if op == "keep":
                ops[f] = {"op": "keep", "value": fields[f]}
            elif op == "delete":
                ops[f] = {"op": "delete", "value": None}
            else:
                res = (change if op == "change" else blur)(f, fields[f], card, rng)
                if res is None:
                    probs.pop(op)
                    continue
                ops[f] = {"op": op, "value": res[0], "operator": res[1]}
            break

    # restructure: one pill twice a day -> two pills once a day (changes two fields)
    fr, da = fields.get("frequency"), fields.get("dose_amount")
    if (not fully_correct and ops.get("frequency", {}).get("op") == "change" and fr and da and
            fr.get("per_day") in (2, 3) and da["count"] == 1 and rng.random() < 0.3):
        ops["frequency"] = {"op": "change", "value": {"per_day": 1}, "operator": "restructure"}
        ops["dose_amount"] = {"op": "change", "value": {"count": fr["per_day"], "form": da["form"]}, "operator": "restructure"}

    # at most max_changed changes, at least min_mentioned fields said
    changed = [f for f in filled if ops[f]["op"] == "change"]
    rng.shuffle(changed)
    for f in changed[ocfg["max_changed"]:]:
        ops[f] = {"op": "keep", "value": fields[f]}
    said = [f for f in filled if ops[f]["op"] != "delete"]
    deleted = [f for f in filled if ops[f]["op"] == "delete"]
    rng.shuffle(deleted)
    while len(said) < ocfg["min_mentioned"] and deleted:
        f = deleted.pop()
        ops[f] = {"op": "keep", "value": fields[f]}
        said.append(f)

    if not fully_correct:
        for f in empty:
            if rng.random() < ocfg["add_p_per_empty_field"]:
                res = add(f, record, card, rng)
                if res:
                    ops[f] = {"op": "add", "value": res[0], "operator": res[1]}

    n_noise = rng.choices(ncfg["n_choices"], weights=ncfg["n_weights"])[0]
    pool = list(ncfg["operators"])
    if not any(f in NUMERIC_FIELDS and ops.get(f, {}).get("op") in ("keep", "change") for f in FIELDS):
        pool.remove("self_correction")
    noise = rng.sample(pool, n_noise)

    labels = {f: OP_TO_LABEL[o["op"]] for f, o in ops.items()}
    return {"pair_id": f"{record['record_id']}-p{version}", "record_id": record["record_id"],
            "drug": record["drug"], "split": record["split"], "version": version,
            "fully_correct": fully_correct, "ops": ops, "noise": noise, "style": style, "labels": labels}


# ---------------------------------------------------------------- prompt lines

NOISE_TEXT = {
    "distractor": "Add one sentence about something unrelated in your day.",
    "filler": "Use fillers and hesitations (um, like, you know).",
    "self_correction": "Correct yourself once on a number (\"two... no wait,\"), ending on the value given above.",
    "question_back": "End by asking whether you got it right.",
    "other_medication": "Briefly mention another medicine you already take, clearly about that other medicine.",
    "shuffled_order": "Say things out of order, not as a tidy list.",
    "transcript": "Write it like a speech transcript: no punctuation, numbers spelled out as words.",
}


def patient_lines(spec: dict, record: dict) -> tuple[list[str], list[str]]:
    """Lines telling the generator what to say, and the topics not to mention."""
    say, avoid = [], []
    for f in FIELDS:
        o = spec["ops"].get(f)
        name = FIELD_NAMES[f]
        if o is None or o["op"] == "delete":
            avoid.append(name)
            continue
        val = o["value"]
        if o["op"] == "keep":
            say.append(f"- {name}: {render(f, val)} (put it in your own words)")
        elif o["op"] == "change":
            say.append(f"- {name}: you believe {render(f, val)}")
        elif o["op"] == "blur":
            if "vague" in val:
                say.append(f'- {name}: be vague about it, something like "{val["vague"]}"')
            else:
                say.append(f"- {name}: mention only this part: {render(f, val)}")
        elif o["op"] == "add":
            say.append(f"- {name}: you also believe {render(f, val)}")
    return say, avoid
