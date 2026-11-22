"""Stages 2-3: doctor texts (with round-trip check) and patient texts (with spec check).

python -m data_gen.generate --pilot --mock      # dry run, no API calls
python -m data_gen.generate --pilot             # real pilot: generator (OpenAI) + verifier (local or API)
python -m data_gen.generate                     # full run
"""
from __future__ import annotations

import argparse
import random

from .common import DATA, load_card, load_cfg, prompt, read_jsonl, write_jsonl
from .edit_ops import LENGTH_WORDS, NOISE_TEXT, patient_lines, sample_spec, sample_styles
from .llm import LLM
from .schema import FIELD_NAMES, FIELDS, render
from .verify import check_doctor, check_patient, perfect_doctor_reading, perfect_patient_reading, verifier_prompt

DOCTOR_SPACE = {
    "role": ["physician", "pharmacist", "discharge nurse"],
    "channel": ["spoken counselling", "a written discharge note"],
    "register": ["warm", "plain", "clinical"],
    "order": ["in the order listed", "in a natural order that suits you"],
    "number_style": ["digits (500 mg)", "words (five hundred milligrams)"],
    "length": ["concise", "detailed"],
}


def doctor_attrs(record: dict, cfg: dict, rng: random.Random) -> dict:
    a = {k: rng.choice(v) for k, v in DOCTOR_SPACE.items()}
    fr = record["fields"]["frequency"]
    convertible = "per_day" in fr and fr["per_day"] in (1, 2, 4) or \
        ("per_day" in fr and fr["per_day"] == 3 and cfg["equivalence"]["tid_equals_q8h"]) or \
        (isinstance(fr.get("every_hours"), int) and 24 % fr["every_hours"] == 0)
    a["frequency_style"] = rng.choice(["times per day", "an interval in hours"]) if convertible else "exactly as listed"
    return a


def doctor_prompt(record: dict, a: dict) -> str:
    lines = "\n".join(f"- {FIELD_NAMES[f]}: {render(f, v)}" for f, v in record["fields"].items() if v is not None)
    return prompt("doctor_v1.txt").format(drug=record["drug"], lines=lines, **a)


def patient_prompt(spec: dict, record: dict) -> str:
    say, avoid = patient_lines(spec, record)
    s = spec["style"]
    noise = "\n".join(NOISE_TEXT[n] for n in spec["noise"])
    return prompt("patient_v1.txt").format(
        speaker=s["speaker"], drug=record["drug"], literacy=s["literacy"], english=s["english"],
        register=s["register"], confidence="sure of yourself" if s["confidence"] == "sure" else "a little unsure, hedging",
        length_words=LENGTH_WORDS[s["length"]], channel=s["channel"], say_lines="\n".join(say),
        avoid=", ".join(avoid) if avoid else "nothing in particular", noise_lines=noise)


def _mock_doctor(record):
    return {"text": " ".join(f"{FIELD_NAMES[f].capitalize()}: {render(f, v)}." for f, v in record["fields"].items() if v)}


def _mock_patient(spec, record):
    say, _ = patient_lines(spec, record)
    return {"text": " ".join(l.lstrip("- ") for l in say)}


def run_doctor(records, cfg, gen, ver, rng, tries=3):
    out = []
    for r in records:
        for attempt in range(1, tries + 1):
            a = doctor_attrs(r, cfg, rng)
            p = doctor_prompt(r, a)
            text = gen.json(p, meta={"stage": "doctor", "record_id": r["record_id"], "attempt": attempt},
                            mock_answer=lambda: _mock_doctor(r))["text"]
            if ver is None:  # verifier not available: keep the text, verify later with --verify-only
                ok, bad, ext = None, [], None
                break
            ext = ver.json(verifier_prompt(text), meta={"stage": "verify_doctor", "record_id": r["record_id"]},
                           mock_answer=lambda: perfect_doctor_reading(r))
            ok, bad = check_doctor(ext, r, cfg["equivalence"]["tid_equals_q8h"])
            if ok:
                break
        out.append({"record_id": r["record_id"], "text": text, "attrs": a, "ok": ok, "attempts": attempt,
                    "mismatches": bad, "verifier_reading": ext, "prompt_version": "doctor_v1",
                    "gen_model": gen.cfg["model"], "ver_model": ver.cfg["model"] if ver else None})
        print(f"doctor {r['record_id']}: {'unverified' if ok is None else 'ok' if ok else 'FAILED'} after {attempt}")
    return out


def run_patient(records, doctors, cfg, gen, ver, rng, n_versions, tries=2):
    by_id = {d["record_id"]: d for d in doctors if d["ok"] is not False}
    kept, dropped = [], []
    for r in records:
        if r["record_id"] not in by_id:
            continue
        card = load_card(r["drug"])
        for v, style in enumerate(sample_styles(n_versions, rng)):
            spec = sample_spec(r, card, cfg, rng, v, style)
            p = patient_prompt(spec, r)
            for attempt in range(1, tries + 1):
                text = gen.json(p, meta={"stage": "patient", "pair_id": spec["pair_id"], "attempt": attempt},
                                mock_answer=lambda: _mock_patient(spec, r))["text"]
                if ver is None:
                    ok, bad, ext = None, [], None
                    break
                ext = ver.json(verifier_prompt(text), meta={"stage": "verify_patient", "pair_id": spec["pair_id"]},
                               mock_answer=lambda: perfect_patient_reading(spec))
                ok, bad = check_patient(ext, spec, r, cfg["equivalence"]["tid_equals_q8h"])
                if ok:
                    break
            row = dict(spec, text=text, doctor_text=by_id[r["record_id"]]["text"], ok=ok, attempts=attempt,
                       mismatches=bad, verifier_reading=ext, prompt_version="patient_v1",
                       gen_model=gen.cfg["model"], ver_model=ver.cfg["model"] if ver else None)
            (kept if ok is not False else dropped).append(row)
    print(f"patient texts: {len(kept)} kept, {len(dropped)} dropped")
    return kept, dropped


def verify_only(base, records, cfg, ver):
    """Verify texts generated with --no-verify. Patient texts of a failed doctor text are dropped."""
    tid = cfg["equivalence"]["tid_equals_q8h"]
    recs = {r["record_id"]: r for r in records}
    doctors = read_jsonl(base / "doctor.jsonl")
    for d in doctors:
        r = recs[d["record_id"]]
        d["verifier_reading"] = ver.json(verifier_prompt(d["text"]), meta={"stage": "verify_doctor", "record_id": r["record_id"]},
                                         mock_answer=lambda: perfect_doctor_reading(r))
        d["ok"], d["mismatches"] = check_doctor(d["verifier_reading"], r, tid)
        d["ver_model"] = ver.cfg["model"]
    good = {d["record_id"] for d in doctors if d["ok"]}
    kept, dropped = [], []
    for p in read_jsonl(base / "patient_unverified.jsonl"):
        r = recs[p["record_id"]]
        if p["record_id"] not in good:
            p["ok"], p["mismatches"] = False, ["doctor text failed the round trip"]
        else:
            p["verifier_reading"] = ver.json(verifier_prompt(p["text"]), meta={"stage": "verify_patient", "pair_id": p["pair_id"]},
                                             mock_answer=lambda: perfect_patient_reading(p))
            p["ok"], p["mismatches"] = check_patient(p["verifier_reading"], p, r, tid)
        p["ver_model"] = ver.cfg["model"]
        (kept if p["ok"] else dropped).append(p)
    write_jsonl(base / "doctor.jsonl", doctors)
    write_jsonl(base / "patient.jsonl", kept)
    write_jsonl(base / "patient_dropped.jsonl", dropped)
    print(f"doctor texts: {len(good)}/{len(doctors)} pass; patient texts: {len(kept)} kept, {len(dropped)} dropped")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--mock", action="store_true", help="no API calls: template texts and a perfect verifier")
    ap.add_argument("--no-verify", action="store_true", help="generate only; texts go to patient_unverified.jsonl")
    ap.add_argument("--verify-only", action="store_true", help="verify texts made earlier with --no-verify")
    args = ap.parse_args()
    cfg = load_cfg()
    rng = random.Random(cfg["seed"] + 1)
    base = DATA / "pilot" if args.pilot else DATA
    if args.mock:
        base = base / "mock"
    records = read_jsonl((DATA / "pilot" if args.pilot else DATA) / "records.jsonl")
    n = cfg["pilot"]["versions_per_record"] if args.pilot else cfg["versions_per_record"]
    ver = None if args.no_verify else LLM("verifier", cfg, mock=args.mock, log_dir=base / "logs")
    if args.verify_only:
        verify_only(base, records, cfg, ver)
        print("usage:", {"verifier": ver.usage})
        return
    gen = LLM("generator", cfg, mock=args.mock, log_dir=base / "logs")

    doctors = run_doctor(records, cfg, gen, ver, rng)
    write_jsonl(base / "doctor.jsonl", doctors)
    kept, dropped = run_patient(records, doctors, cfg, gen, ver, rng, n)
    if ver is None:
        write_jsonl(base / "patient_unverified.jsonl", kept)
        print("Not verified yet. When the verifier is running: python -m data_gen.generate --verify-only" + (" --pilot" if args.pilot else ""))
    else:
        write_jsonl(base / "patient.jsonl", kept)
        write_jsonl(base / "patient_dropped.jsonl", dropped)
    print("usage:", {"generator": gen.usage, "verifier": ver.usage if ver else None})


if __name__ == "__main__":
    main()
