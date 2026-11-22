"""Stage 1b: sample structured prescription records from checked drug cards.

python -m data_gen.sample_records --pilot          # 2 records per pilot drug -> Data/pilot/records.jsonl
python -m data_gen.sample_records                  # 10 records per drug -> Data/records.jsonl
"""
from __future__ import annotations

import argparse
import copy
import random

from .common import DATA, load_card, load_cfg, load_drugs, write_jsonl
from .schema import CORE_FIELDS, FIELDS

OPTIONAL = [f for f in FIELDS if f not in CORE_FIELDS]


def _strip(v):
    """Drop 'source' keys from a card value."""
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if k != "source"}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    return v


def _optional_value(field: str, card_entry: dict, rng: random.Random):
    v = copy.deepcopy(_strip(card_entry["value"]))
    if field == "interactions" and len(v["items"]) > 2:
        v["items"] = rng.sample(v["items"], 2)
    if field == "warning_signs":
        g = rng.choice(v["groups"])
        syms = g["symptoms"] if len(g["symptoms"]) <= 4 else rng.sample(g["symptoms"], rng.choice([2, 3, 4]))
        v = {"groups": [{"symptoms": syms, "action": g["action"]}]}
    if field == "administration" and len(v["tags"]) > 2 and rng.random() < 0.5:
        v["tags"] = rng.sample(v["tags"], 2)
    return v


def sample_record(card: dict, drug: dict, idx: int, cfg: dict, rng: random.Random) -> dict:
    regimens = card["regimens"]
    reg = regimens[idx % len(regimens)]                 # cycle so every regimen is used
    fields = {f: None for f in FIELDS}
    fields["strength"] = _strip(reg["strength"])
    fields["dose_amount"] = _strip(reg["dose_amount"])
    fields["frequency"] = _strip(reg["frequency"])
    fields["duration"] = _strip(rng.choice(reg["durations"]))

    available = [f for f in OPTIONAL if card.get(f)]
    chosen = [f for f in available if rng.random() < cfg["optional_field_p"][f]]
    rest = [f for f in available if f not in chosen]
    rng.shuffle(rest)
    while len(CORE_FIELDS) + len(chosen) < 5 and rest:  # at least 5 filled fields
        chosen.append(rest.pop())
    rng.shuffle(chosen)
    chosen = chosen[: 9 - len(CORE_FIELDS)]             # at most 9
    for f in chosen:
        fields[f] = _optional_value(f, card[f], rng)

    return {"record_id": f"{drug['key']}-{idx:02d}", "drug": drug["key"], "class": drug["class"],
            "split": drug["split"], "regimen": reg["name"], "fields": fields,
            "card_status": card.get("status"), "label_set_id": card["label"]["set_id"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    args = ap.parse_args()
    cfg = load_cfg()
    rng = random.Random(cfg["seed"])
    drugs = [d for d in load_drugs() if d.get("pilot")] if args.pilot else load_drugs()
    n = cfg["pilot"]["records_per_drug"] if args.pilot else cfg["records_per_drug"]
    out = []
    for d in drugs:
        card = load_card(d["key"])
        for i in range(n):
            out.append(sample_record(card, d, i, cfg, rng))
    path = DATA / ("pilot" if args.pilot else "") / "records.jsonl"
    write_jsonl(path, out)
    print(f"{len(out)} records -> {path}")


if __name__ == "__main__":
    main()
