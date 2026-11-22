"""Stage 4: the verifier reads a text back into fields; code compares that with what was intended.

Doctor texts must match the record on every field (round trip).
Patient texts must match the spec: keep -> record value, change -> changed value,
blur -> vague or a subset, delete/empty -> not mentioned, add -> the added value.
"""
from __future__ import annotations

from .common import prompt
from .schema import (ACTIONS, ADMIN, AGENTS, FIELD_DOCS, FIELDS, FOOD, MISSED, RULES, is_subset, same_value)


def verifier_prompt(text: str) -> str:
    return prompt("verifier_v1.txt").format(
        field_docs="\n".join(f"- {f}: {FIELD_DOCS[f]}" for f in FIELDS),
        food_tags=", ".join(FOOD), admin_tags=", ".join(ADMIN), agents=", ".join(AGENTS),
        rules=", ".join(RULES), actions=", ".join(ACTIONS), missed_tags=", ".join(MISSED),
        text=text.replace('"""', "'''"), keys=", ".join(FIELDS))


def _get(ext: dict, f: str):
    e = (ext or {}).get(f) or {}
    return e.get("status", "not_mentioned"), e.get("value")


def _safe(fn, *a):
    try:
        return bool(fn(*a))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def check_doctor(ext: dict, record: dict, tid_equals_q8h: bool = True) -> tuple[bool, list[str]]:
    bad = []
    for f in FIELDS:
        want, (status, val) = record["fields"].get(f), _get(ext, f)
        if want is None:
            if status != "not_mentioned":
                bad.append(f"{f}: not in the record but the text says {status}")
        elif status != "stated" or not _safe(same_value, f, val, want, tid_equals_q8h):
            bad.append(f"{f}: expected {want}, verifier read {status} {val}")
    return not bad, bad


def check_patient(ext: dict, spec: dict, record: dict, tid_equals_q8h: bool = True) -> tuple[bool, list[str]]:
    bad = []
    for f in FIELDS:
        o, rec = spec["ops"].get(f), record["fields"].get(f)
        status, val = _get(ext, f)
        op = o["op"] if o else "absent"
        if op in ("delete", "absent"):
            ok = status == "not_mentioned"
        elif op in ("keep", "change", "add"):
            ok = status == "stated" and _safe(same_value, f, val, o["value"], tid_equals_q8h)
        elif op == "blur":
            if "vague" in o["value"]:
                ok = status == "vague" or (status == "stated" and _safe(is_subset, f, val, rec))
            else:
                ok = status == "vague" or (status == "stated" and (_safe(same_value, f, val, o["value"], tid_equals_q8h)
                                                                   or _safe(is_subset, f, val, rec)))
        else:
            ok = False
        if not ok:
            bad.append(f"{f}: op {op}, expected {o['value'] if o else None}, verifier read {status} {val}")
    return not bad, bad


# ------------------------------------------------ perfect readings, used by the mock verifier in dry runs

def perfect_doctor_reading(record: dict) -> dict:
    return {f: ({"status": "stated", "value": v} if v is not None else {"status": "not_mentioned", "value": None})
            for f, v in record["fields"].items()}


def perfect_patient_reading(spec: dict) -> dict:
    out = {}
    for f in FIELDS:
        o = spec["ops"].get(f)
        if o is None or o["op"] == "delete":
            out[f] = {"status": "not_mentioned", "value": None}
        elif o["op"] == "blur" and "vague" in o["value"]:
            out[f] = {"status": "vague", "value": None}
        else:
            out[f] = {"status": "stated", "value": o["value"]}
    return out
