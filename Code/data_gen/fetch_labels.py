"""Stage 1a: fetch one current oral label per drug from openFDA and keep the sections the cards need.

Run on your PC (the workspace that wrote this code cannot reach api.fda.gov):
    python -m data_gen.fetch_labels            # all 40 drugs -> Data/raw/labels/<drug>.json
    python -m data_gen.fetch_labels --only metformin ibuprofen

Limits without a key: 240 requests/minute, 1,000/day (https://open.fda.gov/apis/authentication).
Set OPENFDA_API_KEY to raise the daily limit. This script makes at most 3 requests per drug.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import requests

from .common import DATA, load_drugs

API = "https://api.fda.gov/drug/label.json"
SECTIONS = ["dosage_and_administration", "dosage_forms_and_strengths", "how_supplied", "information_for_patients",
            "patient_medication_information", "spl_patient_package_insert", "spl_medguide", "boxed_warning",
            "warnings_and_cautions", "warnings", "drug_interactions", "overdosage", "indications_and_usage"]
PATIENT = ["spl_medguide", "patient_medication_information", "information_for_patients", "spl_patient_package_insert"]


def _q(s: str) -> str:
    """openFDA query syntax: '+' for spaces, %22 for quotes (built by hand so '+' is not re-encoded)."""
    return s.replace(" ", "+").replace('"', "%22")


def _query(names: list[str], rx_only: bool) -> list[dict]:
    terms = " ".join(f'openfda.generic_name.exact:"{n}"' for n in names)
    search = f'({terms}) AND openfda.route:"ORAL"'
    if rx_only:
        search += ' AND openfda.product_type:"HUMAN PRESCRIPTION DRUG"'
    url = f"{API}?search={_q(search)}&limit=25"
    if os.environ.get("OPENFDA_API_KEY"):
        url += f"&api_key={os.environ['OPENFDA_API_KEY']}"
    for attempt in range(5):  # retry rate limits and server errors
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return []
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json().get("results", [])
    r.raise_for_status()
    return []


def _score(r: dict, names: list[str]) -> tuple:
    of = r.get("openfda", {})
    exact = (of.get("generic_name") or [""])[0].upper() in names
    rx = (of.get("product_type") or [""])[0] == "HUMAN PRESCRIPTION DRUG"
    return (exact, rx, bool(r.get("dosage_and_administration")), any(r.get(k) for k in PATIENT), r.get("effective_time", ""))


def fetch(drug: dict) -> dict | None:
    names = [n.upper() for n in drug["openfda_names"]]
    res = _query(names, rx_only=True) or _query(names, rx_only=False)
    if not res:
        return None
    best = max(res, key=lambda r: _score(r, names))
    of = best.get("openfda", {})
    out = {"drug": drug["key"], "set_id": best.get("set_id"), "effective_time": best.get("effective_time"),
           "generic_name": (of.get("generic_name") or [""])[0], "brand_name": (of.get("brand_name") or [""])[0],
           "product_type": (of.get("product_type") or [""])[0], "candidates": len(res)}
    for k in SECTIONS:
        if best.get(k):
            out[k] = "\n".join(best[k])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    outdir = DATA / "raw" / "labels"
    outdir.mkdir(parents=True, exist_ok=True)
    found, missing, failed = [], [], []
    for d in load_drugs():
        if args.only and d["key"] not in args.only:
            continue
        try:
            lab = fetch(d)
        except Exception as e:  # keep going; report at the end
            print(f"{d['key']:<24} ERROR {e}")
            failed.append(d["key"])
            continue
        if lab is None:
            print(f"{d['key']:<24} NOT FOUND")
            missing.append(d["key"])
            continue
        found.append(d["key"])
        json.dump(lab, open(outdir / f"{d['key']}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        has = ",".join(k for k in SECTIONS if k in lab)
        print(f"{d['key']:<24} {lab['generic_name']:<40} {lab['product_type']:<26} {lab['effective_time']}  {has}")
        time.sleep(0.5)
    print(f"\nlabels saved: {len(found)}; not found: {missing or 'none'}; errors: {failed or 'none'}")
    if not found:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
