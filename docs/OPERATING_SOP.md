# Operating SOP

## Before A Batch

1. Confirm the exact email template and campaign context.
2. Confirm target persona and product category.
3. Collect examples of good and bad lines if available.
4. Choose a tone profile.
5. Make sure the CSV has `company_name` and `website_url`.
6. Add optional manual notes when available: LinkedIn observation, app flow observation, screenshots, recent news, competitor context.

## Running A Batch

```bash
python cli.py --input path/to/leads.csv --output data/output/review.xlsx --campaign-context "Campaign context here" --reuse-duplicate-personalization --client-batch-output --tone-profile friction_first
```

## Review Checklist

Start in the `Review` tab.

Check:

- Is the sendability decision `Send`, `Edit`, or `Reject`?
- Are there hard-fail reasons?
- Are there soft-edit reasons?
- Is the surface correctness `Correct`, `Review`, or `Wrong`?
- Does the line flow into the template preview?
- Does it contain one clear observation?
- Does it tie to conversion, activation, retention, bookings, trust, signup completion, or drop-off?
- Is the claim backed by evidence?
- Are there em dashes or generic praise?
- Is the row marked for manual review?
- Is the visual confidence low?
- Is an app walkthrough recommended?

## Manual Review Priority

Review first:

1. Rows marked `Reject` by the sendability gate.
2. Rows marked `Edit` by the sendability gate.
3. Rows marked `Review`.
4. App-first companies without app walkthrough notes.
5. Low-confidence visual findings.
6. Weak evidence rows.
7. Rows using app-store/listing evidence as the main angle.
8. Broad-positioning rows.

## Human Edit Goldset

When you manually review rows, set:

- `human_decision`: send, edit, or reject.
- `edited_line`: the final human-edited line, if changed.
- `edit_reason_category`: why the row needed review.
- `edit_notes`: short explanation, especially for client feedback.

In the web app, choose a goldset split and click `Save reviewed rows to goldset`. This appends examples under `data/goldset/` so future prompt and tone-profile changes can be tested against real edits.

Goldset splits:

- `reviewed_examples`: normal reviewed output.
- `frozen_eval_set`: locked regression examples for prompt/model comparisons.
- `candidate_training_set`: examples that may later be used for tuning.

Do not put every reviewed row into the frozen eval set. Use it for stable, representative examples across product types, surfaces, Send/Edit/Reject decisions, and failure categories.

## Delivery

Deliver the workbook only after:

- all client-delivery rows are `Send` or manually approved
- any `Wrong` surface row is rewritten or rejected
- hard-fail rows are not delivered
- all obvious generic lines are fixed
- weak rows are either improved or clearly marked
- duplicate companies use consistent personalization
- no API keys or local paths are visible
- the sample/template preview reads naturally
