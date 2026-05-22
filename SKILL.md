# SKILL.md

## Skill: Outbound Personalization Workflow Builder

This skill describes how an AI coding/research agent should contribute to this project.

---

## Purpose

Help build, maintain and improve a local/productized outbound workflow that turns lead data into evidence-backed, reviewable, client-safe personalized lines for high conversion rates so the business sending the line can earn the most amount of customers possible.

The AI agent should not behave like a random generator.

---

## Core Capabilities

The agent must improve:

- data normalization
- lead quality
- research/enrichment
- app/website/review evidence extraction
- multi-shot opener generation
- QC/sendability evaluation
- sales-principles
- human review workflow
- goldset/eval saving
- client-safe export
- runtime/cost logging
- browser research reliability
- documentation and tests

---

## Workflow Mental Model

The expected pipeline is:

```text
Lead input
-> preserve original columns
-> normalize company/contact/domain/app fields
-> detect duplicates and mismatches
-> research/enrichment
-> evidence extraction
-> lead quality scoring
-> angle selection
-> multi-shot opener generation
-> sales-principles scoring
-> recommended opener selection
-> QC/sendability per option
-> human review
-> goldset/eval saving
-> review export
-> client-safe delivery export
-> campaign feedback import
```

---

## Writing Skill

When generating or evaluating openers:

An example of a Good opener:

```text
I was checking out [company] and noticed [specific signal], which could mean [business implication/tension].
```

That does not mean to just use that opener but use things in the same ballpark as that just the core principles behind it.

Do not generate:

- generic praise
- fake familiarity
- unsupported claims
- technical audit language
- overly long lines
- multiple unrelated ideas
- blog commentary unless directly tied to conversion or user behavior

---

## Evaluation Skill

Every opener option should be scored on:

- evidence strength
- specificity
- surface correctness
- business implication
- outcome bridge
- template fit
- tone fit
- salesiness
- fake familiarity
- unsupported claims
- commercial relevance

The system should prefer false negatives over false sends.

It is better to mark a weak line Edit/Reject than to send a dangerous line.

---

## Research Skill

Research should prioritize:

- app store reviews
- Play Store reviews
- any kind of review
- website homepage
- pricing
- case studies
- testimonials
- conversion path
- onboarding/friction signals
- CTA visibility
- trust/proof gaps
- positioning clarity
- relevant recent news only if traceable

Avoid:

- low-value blog commentary
- unsupported funding/traffic guesses
- technical details with no commercial implication

---

## Enrichment Skill

Useful enrichment fields:

- revenue model
- target customer
- app/product type
- source surface
- company domain
- app store link
- Play Store link
- email verification status
- website tech stack
- traffic availability
- funding/news if verified
- lead quality flags

Low-confidence enrichment must not feed final copy.

---

## Browser Research Skill

Browser checks should be:

- optional
- preflighted
- worker-isolated when needed
- fail-safe
- low-noise

If browser research fails:

- do not fail the batch
- mark visual evidence unavailable
- continue with HTTP/app-store research
- log one clear warning

---

## Testing Skill

Add tests for:

- input column preservation
- delivery export filtering
- review export completeness
- multi-shot option scoring
- goldset saving
- signal-to-implication scoring
- app-first surface correctness
- weak evidence softening
- mismatch detection
- email verifier no-op
- provider failure handling
- browser preflight fallback

Do not rely only on compile checks.

---

## Output Hygiene Skill

Before claiming a feature is complete, verify:

- app still starts
- sample batch runs
- Excel/CSV output opens
- review UI is usable
- delivery export is clean
- rejected rows are not delivered
- goldset stores relevant data
- tests pass

---

## Performance Skill

Monitor:

- API requests per lead
- API requests per unique company
- token count
- cache hit/miss
- total cost
- runtime
- slowest rows
- browser failures
- provider 429s

Optimize by:

- bundling related calls
- preserving writer/judge separation
- using stable prompt blocks
- caching by company/domain/prompt hash
- reusing duplicate company research
- limiting browser checks in large batches

Target:

- quality mode: 2-4 model calls per unique company where possible
- deep mode can use more, but must justify it
