# Quality Benchmark

Use this sheet of metrics to decide whether the workflow is improving.

## Batch Metrics

Track per batch:

- total leads
- unique companies
- generated lines
- ready rows
- review rows
- research-only rows
- average QC score
- rows with source URLs
- rows with high/medium/low visual confidence
- rows requiring app walkthrough
- leads with `no_sendable_option`
- average per-option sendability score
- average per-option sales-principles score
- share of selected openers from option 1, 2, 3, or custom

## Human Review Metrics

Track:

- percentage usable without edit
- percentage usable after light edit
- percentage needing full rewrite
- percentage rejected
- most common failure flags
- average review time per lead

## Quality Rubric

Score every sampled line 1 to 5:

1. Not usable: generic, unsupported, or wrong.
2. Weak: accurate but vague or awkward.
3. Usable with edit: evidence-backed but tone needs work.
4. Good: specific, natural, and tied to outcome.
5. Excellent: feels manually researched and naturally fits the template.

For multi-shot batches, score each option separately before judging the row. A weak option should not inherit the score of a stronger option on the same lead.

## Sales-Principles Checks

The deterministic sales-principles layer is a compact rubric, not copied sales-book content. It checks:

- concrete specificity over cleverness
- one clear insight
- friction/proof/positioning relevance over generic praise
- natural bridge to drop-off, activation, conversion, bookings, retention, trust, or user behaviour
- no fake app familiarity
- low salesiness
- evidence before claim

## Improvement Loop

After each calibration batch:

1. Collect client comments.
2. Identify repeated failures.
3. Update the tone profile.
4. Add one or two bad examples to the QC prompt/profile.
5. Rerun 10 sample rows before scaling.
