"""Run from Code/:  python -m pytest -q"""
import random
from collections import Counter

import pytest

from data_gen.common import load_card, load_cfg, load_drugs
from data_gen.edit_ops import add, blur, change, patient_lines, sample_spec, sample_styles
from data_gen.generate import doctor_prompt, doctor_attrs, patient_prompt
from data_gen.sample_records import sample_record
from data_gen.schema import FIELDS, is_subset, render, same_value
from data_gen.verify import check_doctor, check_patient, perfect_doctor_reading, perfect_patient_reading

CFG = load_cfg()
PILOT = [d for d in load_drugs() if d.get("pilot")]


def records(n=10, seed=1):
    rng = random.Random(seed)
    return [(sample_record(load_card(d["key"]), d, i, CFG, rng), load_card(d["key"])) for d in PILOT for i in range(n)]


def test_equivalence_table():
    assert same_value("frequency", {"per_day": 2}, {"every_hours": 12})
    assert same_value("frequency", {"per_day": 3}, {"every_hours": 8}, tid_equals_q8h=True)
    assert not same_value("frequency", {"per_day": 3}, {"every_hours": 8}, tid_equals_q8h=False)
    assert same_value("duration", {"kind": "weeks", "n": 1}, {"kind": "days", "n": 7})
    assert same_value("strength", {"value": 500, "unit": "milligrams"}, {"value": 500, "unit": "mg"})
    assert not same_value("strength", {"value": 50, "unit": "mg"}, {"value": 500, "unit": "mg"})
    assert same_value("dose_amount", {"count": 1, "form": "pill"}, {"count": 1, "form": "tablet"})


def test_partial_is_subset():
    ref = {"groups": [{"symptoms": ["skin rash", "fever", "stomach cramps"], "action": "call_doctor_now"}]}
    assert is_subset("warning_signs", {"groups": [{"symptoms": ["rash"], "action": "call_doctor_now"}]}, ref)
    assert not is_subset("warning_signs", {"groups": [{"symptoms": ["rash"], "action": "wait_and_see"}]}, ref)
    assert is_subset("duration", {"kind": "days", "n": 10}, {"kind": "days", "n": 10, "finish_course": True})


def test_records_valid_and_rendered():
    for r, _ in records():
        filled = [f for f in FIELDS if r["fields"][f] is not None]
        assert 5 <= len(filled) <= 9, r["record_id"]
        for f in filled:
            assert render(f, r["fields"][f])


def test_every_operator_runs_on_every_card_field():
    rng = random.Random(0)
    for r, card in records(n=3):
        for f in FIELDS:
            v = r["fields"][f]
            for _ in range(5):
                if v is None:
                    res = add(f, r, card, rng)
                    if res:
                        assert render(f, res[0])
                    continue
                for fn in (change, blur):
                    res = fn(f, v, card, rng)
                    if res:
                        assert render(f, res[0])
                        if fn is change:
                            assert not same_value(f, res[0], v), (f, v, res)


def test_spec_constraints_and_label_mix():
    rng = random.Random(3)
    labels = Counter()
    for r, card in records(n=10):
        for v, style in enumerate(sample_styles(8, rng)):
            s = sample_spec(r, card, CFG, rng, v, style)
            said = [f for f, o in s["ops"].items() if o["op"] != "delete"]
            assert len(said) >= CFG["ops"]["min_mentioned"]
            assert sum(o["op"] == "change" for o in s["ops"].values()) <= CFG["ops"]["max_changed"]
            if s["fully_correct"]:
                assert set(s["labels"].values()) == {"correct"}
            labels.update(s["labels"].values())
    total = sum(labels.values())
    share = {k: labels[k] / total for k in labels}
    # targets from the plan: ~47% correct, 21% omitted, 15% changed, 10% partial, 6% added
    assert 0.38 < share["correct"] < 0.58
    assert 0.14 < share["omitted"] < 0.28
    assert 0.09 < share["changed"] < 0.22
    assert 0.05 < share["partial"] < 0.16
    assert 0.02 < share["added"] < 0.10


def test_verifier_checks():
    rng = random.Random(5)
    r, card = records(n=1)[0]
    assert check_doctor(perfect_doctor_reading(r), r)[0]
    bad = perfect_doctor_reading(r)
    bad["strength"] = {"status": "stated", "value": {"value": 1, "unit": "mg"}}
    assert not check_doctor(bad, r)[0]
    for v in range(20):
        s = sample_spec(r, card, CFG, rng, v, sample_styles(1, rng)[0])
        reading = perfect_patient_reading(s)
        assert check_patient(reading, s, r)[0], s["ops"]
        f = next(iter(s["labels"]))
        reading[f] = {"status": "not_mentioned", "value": None}
        if s["ops"][f]["op"] != "delete":
            assert not check_patient(reading, s, r)[0]


def test_prompts_fill():
    rng = random.Random(7)
    r, card = records(n=1)[0]
    assert "{" not in doctor_prompt(r, doctor_attrs(r, CFG, rng)).split("Return JSON")[0]
    s = sample_spec(r, card, CFG, rng, 0, sample_styles(1, rng)[0])
    p = patient_prompt(s, r)
    assert "Do not mention" in p and "{" not in p.split("Return JSON")[0]
    say, avoid = patient_lines(s, r)
    assert len(say) + len(avoid) == len(FIELDS)
