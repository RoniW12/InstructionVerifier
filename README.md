# InstructionVerifier (TeachBack)

Project proposal: [teachback_proposal_.pdf](teachback_proposal_.pdf)

Synthetic data for field-level error detection in a patient's restatement of medication instructions.
Each pair is a doctor text and a patient text; each of 10 prescription fields gets a label:
correct, partial, omitted, changed or added. Labels come from edits to a structured record, never from the text.

Plan and decisions: see the "TeachBack — data generation plan" doc.

## Folders

```
Code/configs/   gen.yaml (seeds, counts, operator probabilities, models), drugs.yaml (40 drugs, classes, splits)
Code/data_gen/  one module per stage (below)
Code/prompts/   card_v1, doctor_v1, patient_v1, verifier_v1
Code/tests/     python -m pytest -q   (from Code/)
Data/cards/     one drug card per drug; the 5 pilot cards are drafts to check against the label
Data/raw/labels openFDA label sections, written by fetch_labels
Data/pilot/     pilot records, texts, rows
Results/        EDA numbers
```

## Setup (Windows, PowerShell, from the repo root)

```powershell
cd Code
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

For local runs, put keys in your environment or in `.env` (never commit them):

```powershell
$env:OPENAI_API_KEY = "sk-..."          # generator
$env:VERIFIER_API_KEY = "local"         # any string for llama.cpp
```

Verifier: a different model family from the generator. `gen.yaml` points it at an OpenAI-compatible server on
`http://localhost:8080/v1`, for example llama.cpp's `llama-server` running an open instruct model on your GPU.
To use an API instead, change `models.verifier.base_url`, `model` and `api_key_env`.

## Run the pilot on GitHub Actions

1. Add the OpenAI key once as a repo secret: Settings > Secrets and variables > Actions > New repository secret,
   name `OPENAI_API_KEY`. Never put the key in a file in the repo.
2. `models.generator.model` in `Code/configs/gen.yaml` must be a model the key can use. The run checks this first.
3. Actions tab > "TeachBack pilot" > Run workflow. It takes a few minutes: tests, 10 records, 10 doctor texts,
   50 patient texts. Outputs are committed back (`Data/pilot/doctor.jsonl`, `patient_unverified.jsonl`,
   `run-actions.log`) and also attached to the run as an artifact together with every call's prompt and reply.
4. GitHub cannot reach the local verifier, so the texts are unverified. Verify on a PC, from a clone of this repo,
   with the verifier server running (`http://localhost:8080/v1`):

```powershell
git pull
cd Code
python -m data_gen.generate --pilot --verify-only   # -> patient.jsonl, patient_dropped.jsonl
python -m data_gen.build_rows --pilot
```

To run everything locally instead (with the verifier if it is running): put the key in `.env`
(copy `.env.example`) and right-click `run_pilot.ps1` > "Run with PowerShell".

## Pilot (5 drugs, 10 records, 50 patient texts)

```powershell
cd Code
python -m data_gen.fetch_labels --only amoxicillin metformin ibuprofen omeprazole sertraline   # optional: refresh labels
# 1. Check the 5 cards in Data/cards against the label sections; fix values marked CHECK; set "status": "checked".
python -m data_gen.sample_records --pilot          # -> Data/pilot/records.jsonl
python -m data_gen.generate --pilot --mock         # dry run, no API calls (already passes)
python -m data_gen.generate --pilot                # real run -> Data/pilot/doctor.jsonl, patient.jsonl, patient_dropped.jsonl
python -m data_gen.build_rows --pilot              # -> Data/pilot/rows/*.jsonl, Results/eda_pilot_real.json
```

Then both of you label the 50 patient texts by hand (independently) for the audit and kappa.

## Full run

The "Fetch drug labels" workflow fetches the labels for all 40 drugs on GitHub and commits them to
`Data/raw/labels`. It runs by itself when `drugs.yaml` or `fetch_labels.py` is pushed (so on the first push),
or from the Actions tab. No key needed.

```powershell
python -m data_gen.fetch_labels                    # all 40 drugs, under 120 requests (GitHub does this for you, see above)
python -m data_gen.build_cards                     # drafts the other 35 cards; check each one by hand
python -m data_gen.sample_records                  # 400 records
python -m data_gen.generate                        # ~3,200 patient texts
python -m data_gen.build_rows
```

Every call is logged with its prompt, reply, model and token usage in `Data/**/logs/`, so any row can be traced
and the dataset rebuilt. `llm.write_batch_file` / `read_batch_output` support OpenAI's Batch API for the first pass.
