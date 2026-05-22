# PROMPTING_GUIDE.md

## Prompt Architecture

Separate prompts into:

```text
STATIC BLOCK
- system behavior
- output schema
- sales-principles rubric
- QC rules
- tone rules
- template context

DYNAMIC BLOCK
- company evidence
- lead row
- reviews
- app/website observations
```

Keep static blocks stable to maximize prompt caching.

---

## Prompt Caching Rules

Do:

- keep schemas stable
- keep rubrics stable
- avoid rewriting static instructions
- use compact dynamic evidence
- log cache hit/miss if provider supports it

Avoid:

- adding verbose explanations to machine-only outputs

---

## Model Call Structure

Preferred quality mode:

```text
Call 1: research/enrichment
Call 2: generate 2-3 opener options
Call 3: independent QC/sendability/sales-principles judge
```

Optional:

```text
Call 4: final rewrite for selected weak-but-useful option
```

Do not collapse everything into one call by default.

Writer and judge should remain separate for quality.

---

## Output Format

Prefer compact JSON.

Avoid verbose internal explanations.

Use short reason codes where possible.

Example:

```json
{
  "decision": "Edit",
  "reason_codes": ["weak_bridge", "too_assertive_for_evidence"],
  "summary": "Useful signal, but claim needs softer wording."
}
```

---

## Cold Opener Pattern

Preferred:

```text
Observed signal -> business implication -> relevant tension
```

Do not overuse the exact pattern. Keep it natural.

---

## Claim Softening

If evidence is weak:

synonyms of these words or these words:

```text
could be
might be
may be
could be adding friction
```

If evidence is strong (synonyms):

Use carefully:

```text
likely
probably
```

Avoid:

```text
definitely
almost certainly
this is costing you
```

---

## App Usage Rules

Do not say:

```text
I downloaded your app.
I opened your app.
I tried your app.
I loved using your app.
```

Unless a human manually verified actual usage.

Use safer language like:

```text
I was checking out the app listing...
I was looking through the App Store reviews...
I was checking the landing page...
I noticed in the reviews...
```

---

## Review Prompt Rules

The judge should be stricter than the writer.

A judge must be allowed to say:

```text
no_sendable_option
```

Do not force a winner if all options are weak.

---

## Goldset Prompt Rules

Goldset examples should include:

- input evidence
- generated options
- selected option
- rejected options
- human decision
- rewrite
- reason
- why it worked/failed

Goldset is judgment data, not just writing examples.
