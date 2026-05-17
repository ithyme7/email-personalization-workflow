# Goldset And Evals

The goal of the goldset is to stop quality from drifting when prompts, models, detectors, or tone profiles change.

## Splits

- `reviewed_examples.csv`: normal reviewed rows. This is the broad log of human feedback.
- `frozen_eval_set.csv`: locked examples used for regression testing. Do not casually edit or remove these once they represent the target standard.
- `candidate_training_set.csv`: high-quality examples that may later become fine-tuning or preference-tuning data.

## What To Save

Save rows after a human has made a decision:

- `send`: the line is good enough to deliver.
- `edit`: the line had the right idea but needed a rewrite.
- `reject`: the line should not be sent.

For edited rows, fill in:

- `edited_line`
- `edit_reason_category`
- `edit_notes`

The workflow keeps line provenance non-destructive:

- `model_opening_line`: the original model line
- `current_opening_line`: the currently visible/reviewed line
- `edited_line`: the human rewrite
- `final_delivery_line`: the line used for delivery after review

This creates a pair:

- `non_preferred_line`: the original weaker line.
- `preferred_line`: the human-approved or human-edited line.

That pair is useful later for prompt comparison, model bake-offs, and pairwise judging.

## Frozen Eval Set Rules

Add examples that represent the real workload, not only the most dramatic failures.

Include:

- app-first products
- website-first leadgen
- B2B services
- commerce/product pages
- marketplace or booking flows
- strong Send rows
- borderline Edit rows
- clear Reject rows
- wrong-surface examples
- weak-evidence examples
- tone failures
- technical-audit-language failures

## What To Measure Later

The next evaluation layer should track:

- sendability precision: how many `Send` rows survive human review
- edit rate: how often generated lines need rewriting
- reject rate: how often the system should not have generated a deliverable line
- surface correctness: whether the line uses the right research surface
- evidence sufficiency: whether claims are backed by sources/screenshots
- tone match: whether the line sounds like the target client style
- cost per unique company

## Running The Frozen Eval Report

After saving reviewed rows to `frozen_eval_set`, run:

```bash
python eval_runner.py
```

This creates an Excel report under `data/output/evals/` with:

- gate versus human agreement
- send precision
- reject recall
- false-send rows
- surface-correctness rate
- row-level detail for misses

Use this before changing prompts, thresholds, model choice, or client tone profiles.

## Release Gate

Run the gate before treating a new version as ready:

```bash
python eval_runner.py --enforce-gate --fail-on-regression
```

Create or refresh the current baseline intentionally:

```bash
python eval_runner.py --write-baseline
```

Default release thresholds:

- send precision at least 90%
- gate/human agreement at least 78%
- false sends no higher than 0
- surface correctness at least 85%
- app-first surface correctness at least 90% when app-first rows exist

Client feedback imports are saved to `reviewed_examples` or `candidate_training_set` first. Do not import client feedback directly into `frozen_eval_set`; promote examples deliberately after checking they are representative.

## Pairwise Judge Direction

Do not ask a judge model vague questions like “is this good?”

Use pairwise or pass/fail prompts:

- Which line is more sendable for this campaign?
- Which line better fits the provided template?
- Which line is better supported by the evidence?
- Does this line pass the hard-fail rubric?

Only trust an automated judge after checking that it agrees with the frozen eval set.

## Judge Bakeoffs

When you have a useful frozen set and an API key, compare judge models against the same rows:

```bash
python judge_bakeoff.py --models "gemini-3.1-flash-lite,gemini-2.5-flash"
```

The output goes to `data/output/evals/` and reports judge/human agreement per model. Treat this as calibration evidence, not as permission to remove human review.
