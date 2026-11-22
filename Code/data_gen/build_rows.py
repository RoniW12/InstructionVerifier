"""Stage 4b: near-duplicate removal, one training row per scored field, and EDA numbers.

python -m data_gen.build_rows --pilot [--mock]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict

from .common import DATA, ROOT, read_jsonl, write_jsonl
from .schema import FIELDS, LABELS


def _shingles(text: str, k: int = 3) -> set:
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def dedup(pairs: list[dict], threshold: float = 0.8) -> tuple[list[dict], list[str]]:
    """Drop a patient text whose word-trigram Jaccard with an earlier version of the same record is above threshold.
    (Swap for sentence-embedding cosine > 0.95 once sentence-transformers is installed.)"""
    kept, removed, seen = [], [], defaultdict(list)
    for p in pairs:
        sh = _shingles(p["text"])
        if any(len(sh & o) / max(1, len(sh | o)) > threshold for o in seen[p["record_id"]]):
            removed.append(p["pair_id"])
            continue
        seen[p["record_id"]].append(sh)
        kept.append(p)
    return kept, removed


def to_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        for f in FIELDS:
            if f not in p["labels"]:
                continue  # empty field that the patient did not mention: not scored
            o = p["ops"][f]
            rows.append({"pair_id": p["pair_id"], "record_id": p["record_id"], "drug": p["drug"], "split": p["split"],
                         "field": f, "doctor_text": p["doctor_text"], "patient_text": p["text"], "label": p["labels"][f],
                         "op": o["op"], "operator": o.get("operator"), "noise": p["noise"], "style": p["style"],
                         "gen_model": p["gen_model"], "prompt": p["prompt_version"]})
    return rows


def eda(pairs, rows, dropped, removed) -> dict:
    lab = Counter(r["label"] for r in rows)
    per_field = {f: dict(Counter(r["label"] for r in rows if r["field"] == f)) for f in FIELDS}
    plen = [len(p["text"].split()) for p in pairs]
    dlen = [len(t.split()) for t in {p["doctor_text"] for p in pairs}]
    drop_ops = Counter(o["op"] for d in dropped for f, o in d["ops"].items() if any(m.startswith(f + ":") for m in d["mismatches"]))
    return {
        "pairs": len(pairs), "rows": len(rows), "dropped_by_verifier": len(dropped), "near_duplicates_removed": len(removed),
        "label_share": {k: round(lab[k] / max(1, len(rows)), 3) for k in LABELS},
        "label_counts": dict(lab), "per_field": per_field,
        "patient_words": {"min": min(plen, default=0), "mean": round(sum(plen) / max(1, len(plen)), 1), "max": max(plen, default=0)},
        "doctor_words": {"min": min(dlen, default=0), "mean": round(sum(dlen) / max(1, len(dlen)), 1), "max": max(dlen, default=0)},
        "fully_correct_pairs": sum(p["fully_correct"] for p in pairs),
        "noise_counts": dict(Counter(n for p in pairs for n in p["noise"])),
        "mismatched_ops_in_dropped": dict(drop_ops),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    base = DATA / "pilot" if args.pilot else DATA
    if args.mock:
        base = base / "mock"
    pairs, removed = dedup(read_jsonl(base / "patient.jsonl"))
    dropped = read_jsonl(base / "patient_dropped.jsonl")
    rows = to_rows(pairs)
    for split in sorted({r["split"] for r in rows}):
        write_jsonl(base / "rows" / f"{split}.jsonl", [r for r in rows if r["split"] == split])
    stats = eda(pairs, rows, dropped, removed)
    out = ROOT / "Results" / f"eda_{'pilot_' if args.pilot else ''}{'mock' if args.mock else 'real'}.json"
    out.parent.mkdir(exist_ok=True)
    json.dump(stats, open(out, "w"), indent=1)
    print(json.dumps({k: stats[k] for k in ("pairs", "rows", "label_share", "patient_words")}, indent=1))
    print(f"EDA -> {out}")


if __name__ == "__main__":
    main()
