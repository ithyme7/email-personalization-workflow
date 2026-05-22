# RULES.md

## Non-Negotiable Rules

1. Preserve original input columns exactly.
2. Never drop rows silently.
3. Never include Edit/Reject rows in client delivery exports.
4. Never imply personal product/app usage unless manually verified.
5. Never use unsupported claims in final copy.
6. Never use low-confidence enrichment as opener evidence.
7. Never expose local file paths, raw traces or internal detector dumps in client-safe exports.
8. Do not make the review sheet unreadable with internal metrics.
9. Do not build large new features before verifying output quality.
10. Do not compete with low-cost VA work on price; build the system/quality layer.

---

## Copy Rules

Good cold opener copy should be:

- short
- specific
- evidence-backed
- commercially relevant
- conversational
- connected to the pitch
- low-hype
- low-salesiness
- free of em dashes
- free of fake familiarity

Avoid:

```text
I downloaded your app...
I loved using...
I was impressed by...
Your product is powerful...
```

Use lowercase company names in opener copy where it sounds more natural, if client prefers it.

---

## Claim Strength Rules

Use assertive language only when evidence is strong.

Strong evidence can support:

```text
I bet that...
```

Weak/medium evidence should use things like:

```text
could be costing
might be creating
may be causing
could be adding friction
```

Never say things like:

```text
almost certainly
definitely
this is costing you
```

unless evidence is direct and strong.

---

## Surface Correctness Rules

For app-first products:

Prefer:

- App Store
- Google Play
- public reviews
- screenshots
- app onboarding evidence
- app listing evidence

Use website evidence only if:

- app evidence is unavailable
- website evidence is clearly stronger
- website evidence is directly connected to conversion, trust, activation, booking or drop-off

Wrong-surface lines should be Edit or Reject.

---

## Sales-Principles Rules

Use these principles internally:

1. Specificity beats cleverness.
2. One clear insight per opener.
3. Friction beats generic praise.
4. Evidence before claim.
5. No fake familiarity.
6. Low salesiness.
7. Natural bridge into the pitch.
8. Observed signal -> business implication -> relevant tension.

---

## Signal to Implication Bridge

A strong opener should not stop at a surface-level observation.

Pattern:

```text
Observed signal -> business implication -> relevant tension
```

Weak:

```text
Saw you are hiring SDRs.
```

Strong:

```text
Saw you are hiring SDRs. Usually that means the team is trying to increase outbound volume without letting quality collapse.
```

High score:

- concrete signal
- plausible implication
- relevant tension
- connected to pitch

Low score:

- signal only
- generic congratulations
- no business implication

Reject/Edit:

- invented implication
- unsupported assumption
- irrelevant tension

---

## Export Rules

Review export includes all rows.

Delivery export includes only:

- Send rows
- human-approved Edit rows with final opener
- custom approved rewrites

Delivery export excludes:

- Reject rows
- unresolved Edit rows
- unsupported lines
- internal debug fields
- raw detector outputs
- local paths
- browser traces

---

## Runtime Rules

For large batches:

- no Lighthouse by default
- browser checks optional
- bundle API calls
- cache static prompt blocks
- reuse company-level research
- log tokens and requests
- save partial output on provider failure
- avoid repeated Playwright failures
