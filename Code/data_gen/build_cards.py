"""Stage 1a': draft a drug card from saved label sections with the generator model.

python -m data_gen.build_cards                  # every drug with a label and no card yet
python -m data_gen.build_cards --only naproxen

Cards are drafts: both of you check every value and source before records are sampled.
The 5 pilot cards were drafted by hand from the same sections and are already in Data/cards.
"""
from __future__ import annotations

import argparse
import json

from .common import DATA, load_cfg, load_drugs, prompt
from .llm import LLM
from .schema import ACTIONS, ADMIN, AGENTS, FOOD, MISSED, RULES

CARD_FORMAT = json.dumps(json.load(open(DATA / "cards" / "omeprazole.json", encoding="utf-8")), indent=1)
KEEP = {"dosage_and_administration": 9000, "dosage_forms_and_strengths": 1500, "how_supplied": 1500,
        "spl_medguide": 7000, "patient_medication_information": 7000, "information_for_patients": 5000,
        "spl_patient_package_insert": 5000, "boxed_warning": 2000, "warnings_and_cautions": 3000,
        "warnings": 3000, "drug_interactions": 2500}


def card_prompt(label: dict, drug: dict) -> str:
    sections = "\n\n".join(f"## {k}\n{label[k][:n]}" for k, n in KEEP.items() if label.get(k))
    return prompt("card_v1.txt").format(
        drug=drug["key"], card_format=CARD_FORMAT, sections=sections,
        food_tags=", ".join(FOOD), admin_tags=", ".join(ADMIN), agents=", ".join(AGENTS),
        rules=", ".join(RULES), actions=", ".join(ACTIONS), missed_tags=", ".join(MISSED))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    cfg = load_cfg()
    gen = LLM("generator", cfg)
    for d in load_drugs():
        if args.only and d["key"] not in args.only:
            continue
        lab_path, card_path = DATA / "raw" / "labels" / f"{d['key']}.json", DATA / "cards" / f"{d['key']}.json"
        if card_path.exists() or not lab_path.exists():
            continue
        label = json.load(open(lab_path, encoding="utf-8"))
        card = gen.json(card_prompt(label, d), meta={"stage": "card", "drug": d["key"]}, temperature=0)
        card.update({"drug": d["key"], "class": d["class"], "status": "draft",
                     "label": {"set_id": label["set_id"], "effective_time": label["effective_time"],
                               "generic_name": label["generic_name"]}})
        json.dump(card, open(card_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"card drafted: {d['key']}")


if __name__ == "__main__":
    main()
