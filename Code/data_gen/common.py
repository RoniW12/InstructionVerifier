"""Paths, config loading and JSONL helpers."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]          # teachback/
CODE = ROOT / "Code"
DATA = ROOT / "Data"
PROMPTS = CODE / "prompts"


def load_cfg(path: Path | None = None) -> dict:
    return yaml.safe_load(open(path or CODE / "configs" / "gen.yaml", encoding="utf-8"))


def load_drugs() -> list[dict]:
    return yaml.safe_load(open(CODE / "configs" / "drugs.yaml", encoding="utf-8"))["drugs"]


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def write_jsonl(path: Path, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_card(drug: str) -> dict:
    return json.load(open(DATA / "cards" / f"{drug}.json", encoding="utf-8"))


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")
