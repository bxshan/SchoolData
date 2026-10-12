# K12-AII — K-12 AI Index

Experiment code for `Research Design - K12 AII.md`: do LLMs know US K-12 schools without a Wikipedia article worse than those with one?

Inputs: HF `SchoolData/us-k12-schools` (wiki flag, in `data/hf/`) joined to the local NCES master in `SchoolData/data/nces_crawl` (ground truth). Set paths in `config.yaml`.

## Run order
```bash
pip install -r requirements.txt
python -m k12aii build-frame                       # join + derive covariates -> data/frame.parquet
python -m k12aii power                             # minimum detectable gap vs sample size
python -m k12aii sample --n 50                     # matched sample (n per group)
python -m k12aii check-tools --models gpt-4o       # PILOT STEP 1: verify no tool/search leakage
python -m k12aii estimate --sample runs/sample_n50_seed20261004.parquet
python -m k12aii run --sample runs/sample_n50_seed20261004.parquet --run-dir runs/pilot --models gpt-5.5 \
    --tasks kb bias:none bias:frl15 bias:frl85 bias:placebo   # kb = A1-A7 + D1; bias:* = bias probe
python -m k12aii judge --run-dir runs/pilot        # LLM judge for Q5 (config.yaml: judge)
python -m k12aii calibrate-export --run-dir runs/pilot   # fill the 2 human columns, then:
python -m k12aii calibrate-score  --run-dir runs/pilot
python -m k12aii analyze --run-dir runs/pilot      # runs/pilot/analysis/report.md + figure
```
Keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`. Models without a key are skipped. `mock-*` models + `--judge-provider mock` dry-run the pipeline offline (fake results).

`make test` runs the unit + mock end-to-end tests; `make mock` does a full fake dry run.

All prompts and scoring rules are listed in [QUESTIONS.md](QUESTIONS.md). `python -m k12aii baseline` computes the name-only baseline.

## Repeats
GPT-5.5 and recent Claude models reject `temperature`, so outputs are not deterministic. `--repeats k` (or `repeats:` in config) re-asks each (model, school, task) k times; runs are resumable per repeat, regression SEs are clustered by school, counterfactual diffs are averaged over repeats first, and the report adds a run-to-run stability table.

## Bias probe (sub-question 5)
The neutral Q5 describes schools in encyclopedic, evaluation-free prose, so it cannot show bias. A separate `bias:*` task asks for 1-10 ratings (academic, safety, resources, teachers, recommend) and a self-rated familiarity (B0), and forces a best guess so name/location stereotypes show for unknown schools. `bias:none` is regressed on true FRL% (controlling for familiarity); `bias:frl15` / `bias:frl85` tell the model a random poverty level for the same school, giving a causal paired comparison.

## Deviations from the design doc (and why)
- **Matched sampling.** Wiki schools are ~85% high schools; non-wiki are mostly elementary. Sampling equalizes wiki / non-wiki inside every sector x locale x (high vs other) cell; regressions also control for these and log enrollment.
- **No founding year, no Title I.** Neither exists in the NCES master. Easy items A1-A4: public/private, district (public), level, religious affiliation (private); hard items A5-A7: exact grade span, enrollment band, charter status. SES = free/reduced-lunch share (public only; schools with missing FRL excluded).
- **City is in the prompt** (`prompt.include_city`) to disambiguate same-named schools; it is therefore not scored.
- **Weak wiki matches dropped** (fuzzy/geo tiers) so "wiki" really means that school's article.
- **New schools excluded** (`frame.public_statuses`): schools that opened in 2024-25 post-date most model cutoffs.
- **Names normalized** for both groups (`H S`->High School, `Elem.`->Elementary, ...): NCES abbreviations were unevenly spread across groups and would confound recognition. **Territories excluded.** Regressions control for the full 4-way school level.
- Locale: NCES town merged into rural. Private "middle" level is not separable in PSS (elementary/secondary/combined only).
- Judge sees NCES identity facts only, never wiki status or FRL. Reported both as `h2` (any unverifiable specific = risk) and `strict` (contradicts NCES).

## Before the real run
Verify every model ID / release / cutoff in `config.yaml` (marked in design §8), confirm old endpoints still exist, add the newest Gemini, choose a judge outside the tested set (default Claude Opus is also a tested *family* via Sonnet; consider GPT as judge for the Claude rows, or accept and report self-preference risk), and calibrate the judge on >=30-50 items.
