# AGENTS.md

## Project Mission

This project is an AI-assisted outbound personalization and lead-process program.

It is not a simple "AI writes cold email lines" tool.

The goal is to turn messy lead data into reviewed, evidence-backed outbound assets that can be used in real campaigns with as goal to get the best conversion rates possible.

The workflow should help with:

- lead list cleanup
- company/contact normalization
- lead enrichment
- app/website/review research
- multi-shot personalized opener generation
- QC and sendability evaluation
- human review and calibration
- goldset/eval data collection
- client-safe export
- campaign feedback analysis
- eventually upstream lead-process automation

The product should be treated as a local/productized workflow, not a full SaaS platform yet but we should try to build it but not on heavy hardware should run on consumer hardware so highly optimized.

---

## Primary User

The primary operator is Thymen.

The primary client use case is outbound personalization for client campaigns.

The tool may later support multiple clients, each with their own:

- tone profile
- campaign context
- ICP
- personalization rules
- review preferences
- export requirements

---

## Core Product Philosophy

1. Evidence before claims.
2. Quality over volume.
3. Human review is training data.
4. A line can be personalized and still be commercially weak.
5. The system should know when not to trust itself.
6. Review output and delivery output are different things.
7. Low-confidence data must not become confident copy.
8. Preserve original input columns exactly.
9. Never silently drop rows.
10. Build pragmatic local workflow improvements before SaaS complexity.

---

## What Good Looks Like

A good opener:

- starts from a concrete observed signal
- connects that signal to a plausible business implication
- creates a relevant operational or commercial tension
- flows naturally into the campaign pitch
- sounds like a human wrote it
- is short enough for a cold email template
- avoids fake familiarity
- avoids generic praise
- is supported by traceable evidence

Pattern:

```text
Observed signal -> business implication -> relevant tension
```

Example:

Weak:

```text
Saw you are hiring SDRs.
```

Strong:

```text
Saw you are hiring SDRs. Usually that means the team is trying to increase outbound volume without letting quality collapse.
```

---

## What Bad Looks Like

Bad output includes:

- generic praise
- fake app/product usage claims
- unsupported assumptions
- vague UX commentary
- technical audit language in outreach copy
- blog-commentary style observations
- wrong-surface personalization
- long multi-clause lines
- "AI mush"
- overconfident claims based on weak evidence
- delivery exports containing Edit/Reject rows

Examples to avoid:

```text
I loved your app.
I downloaded your app and noticed...
Your product is powerful.
I was impressed by your mission.
I saw your blog post and thought it was interesting.
```

Unless usage was actually verified manually, do not imply personal product use.

---

## Current High-Priority Workflow Layers

1. Input preservation
2. Lead quality scoring
3. Company/contact/domain mismatch detection
4. App Store / Play Store / website research
5. Research/enrichment fields
6. Multi-shot opener generation
7. QC/sendability per opener option
8. Sales-principles evaluation
9. Recommended opener selection
10. Human review
11. Goldset/eval saving
12. Review export vs delivery export separation
13. Runtime/cost/request logging
14. Client-safe packaging

---

## Multi-Shot Rules

For each unique company, generate 2-3 opener options when evidence supports it.

Each option must have its own:

- opener text
- angle type
- evidence
- source URL
- sendability decision
- sendability score
- quality flags
- sales-principles summary
- edit/reject reason

Do not score only the row when multiple opener options exist.

Recommended opener must be selected from evaluated options.

If no option is safe, mark:

```text
no_sendable_option
needs_manual_review
```

---

## Review vs Delivery

Review export:

- includes all rows
- includes Send/Edit/Reject
- includes opener options
- includes evidence
- includes reasons
- includes review fields
- is used for calibration

Delivery export:

- includes only Send or human-approved rows
- excludes Reject
- excludes Edit unless approved final opener exists
- excludes raw traces
- excludes local paths
- excludes noisy internal debug fields
- should be client-safe

Never treat review output as final delivery.

---

## Human Review Loop

Human review is not just correction.

It is calibration data.

Store:

- original generated opener
- all opener options
- selected opener
- non-selected options
- human decision
- edited version
- edit reason category
- reviewer notes
- evidence behind the line
- angle type
- surface type
- prompt/model/version metadata

The system should learn from:

- what was sent
- what was rejected
- what was edited
- why the edit was made
- which non-selected options lost

---

## Goldset Splits

Use separate sets:

- reviewed_examples
- candidate_training_set
- frozen_eval_set

Never train and evaluate on the same examples.

Frozen evals are used for regression testing.

---

## Runtime Rules

The workflow can use high token volume if cost is low, but request count and runtime must be monitored.

Track:

- API requests
- tokens
- cost
- cache hits
- cache misses
- output tokens
- runtime
- calls per lead
- calls per unique company
- browser failures
- provider errors

Optimize for:

- stable prompts
- cacheable static blocks
- bundled calls
- independent writer/judge separation
- low request count without quality collapse

---

## Model Strategy

Use cheaper models for:

- research extraction
- enrichment
- classification
- first-pass drafting
- bulk QC

Use stronger models for:

- final copy
- judge layer
- high-value rows
- difficult tone matching

The workflow should remain model-agnostic.

---

## Browser Research Strategy

Browser checks are useful but must not break the batch.

Preferred architecture:

```text
main app
-> browser worker process
-> Playwright/Chromium
-> JSON/screenshot result
-> main app
```

If browser checks fail:

- do not retry per row forever
- mark visual evidence unavailable
- continue HTTP/app-store research
- warn the user once

---

## What Agents Should Not Do

Do not:

- build full SaaS infrastructure prematurely
- add paid provider dependencies as hard requirements
- rewrite the whole architecture without need
- break original input column preservation
- silently drop rows
- send Edit/Reject rows in delivery export
- use low-confidence traffic/funding/tech-stack as opener evidence
- expose raw traces/local paths to clients
- over-optimize cost at the expense of review quality
- mention internal dev tooling such as Codex to clients unless explicitly needed

---

## Definition of Done

A feature is not done until it works through:

```text
input
-> processing
-> review UI/export
-> goldset if applicable
-> client-safe export if applicable
-> tests
```

For workflow features, end-to-end behavior matters more than isolated module tests.
