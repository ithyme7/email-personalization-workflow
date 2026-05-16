# Client Training Guide

Use the client training template when you want a client to teach the workflow what good personalization sounds like.

The client should not need to understand fine-tuning, evals, DPO, or model training. They only need to mark examples.

## What To Send

Send the Excel file created from the `Client Training` tab in the web app.

Suggested message:

```text
I've attached a short feedback template.

For each line, just choose:
- Send as is
- Rewrite
- Reject

If you choose Rewrite, please write the version you'd actually want to send.
The most useful feedback is not a long explanation, but a few strong examples of what sounds right and what sounds wrong.

I'll use the completed sheet to tune the workflow/model around your preferred tone and decision criteria.
```

## What The Client Fills In

- `client_decision`: Send as is, Rewrite, or Reject.
- `client_rewrite`: the version they would actually send. Only needed for Rewrite.
- `main_reason`: the main reason the line worked or failed.
- `surface_to_focus_on`: where the observation should come from.
- `evidence_or_context`: optional proof, source, app-flow note, review theme, or context.
- `what_good_should_sound_like`: plain-language style guidance.
- `final_notes`: any extra nuance.

## Why Rewrites Matter

Rewrites are the strongest training signal.

They create a pair:

- original line: non-preferred output
- client rewrite: preferred output

That pair can later be used for:

- prompt tuning
- tone profile tuning
- model bake-offs
- fine-tuning
- preference tuning

## Simple Rules For Good Feedback

Ask the client to:

- rewrite only lines they would genuinely prefer
- keep rewrites close to the real cold email style
- avoid long explanations when a rewrite would be clearer
- reject lines that use the wrong surface or unsupported evidence
- mark generic lines as Too generic
- mark overly technical lines as Too technical

## Where Imported Feedback Goes

In the web app, upload the completed template in `Client Training`.

Recommended destination:

- `candidate_training_set` for normal client feedback
- `frozen_eval_set` only for locked examples that should be used to test future changes
- `reviewed_examples` for general notes and non-final review data

Do not use every client example for fine-tuning. First collect enough consistent examples, then select the cleanest ones.
