# Go-To-Market Plan

## Positioning

Evidence-first personalization for outbound teams — now with automated follow-up sequences, A/B testing, and send-time optimization.

The productized service turns lead lists into reviewed, source-backed cold-email openers. It is not positioned as "AI writes emails." It is positioned as faster research, stronger evidence, a safer review process, and automated post-send workflows for high-quality outbound.

## Ideal First Customers

- Founders or growth teams sending low-volume, high-quality outbound.
- Agencies running outbound campaigns for clients.
- Sales teams that care about personalization but do not want generic AI copy.
- App/mobile teams where UX, onboarding, conversion, and activation angles are commercially relevant.
- Teams running multi-touch campaigns who need automated follow-up sequences.
- Growth teams running A/B experiments on messaging angles.

## Core Offer

Send a CSV. Receive a reviewed workbook with:

- personalized first lines
- evidence used for each line
- source URLs
- confidence and quality flags
- manual-review notes
- duplicate-company handling
- dashboard summary
- **optional: optimal send-time per lead**
- **optional: 4-step follow-up sequences** (Value → Social Proof → Direct Ask → Breakup)
- **optional: A/B experiment traffic splitting** (Thompson Sampling + chi-squared significance)

## Pricing Tests

Start as a productized service, not SaaS.

- **Trial batch**: 25 to 50 leads for a low fixed price.
- **Standard**: 100 leads per batch, priced based on research depth and manual review.
- **Premium**: includes app walkthroughs, LinkedIn/person research notes, tone-profile tuning, follow-up sequences, and A/B test setup.
- **Ongoing optimization**: monthly retainer for sequence refinement, A/B experiment analysis, and goldset maintenance.
- **Build fee**: charge separately if a client wants their own dedicated workflow or custom dashboard.

The software should stay behind the service until the buying pattern is clear.

## Sales Call Flow

1. Ask what "good personalization" means to them.
2. Ask for 3 good examples and 3 bad examples.
3. Ask where the line is used in their exact email template.
4. Ask how much manual research they currently do per lead.
5. Ask whether they send one email or run multi-touch sequences.
6. Ask what errors would make the output unusable.
7. Show the workbook: Review tab first, then Evidence, then Dashboard.
8. Demo send-time optimization and sequence generation if they're interested.
9. Offer a calibration batch before discussing scale.

## Differentiators

- Evidence-first, not copy-first.
- Weak evidence is flagged instead of hidden.
- Visual and browser checks are included.
- Tone profiles can be tuned per customer.
- The output is human-reviewable and auditable.
- **Send-time optimization** increases open rates by 20-40% (industry benchmarks).
- **Automated follow-up sequences** multiply touchpoints without manual effort.
- **A/B testing framework** provides statistical proof of which angles convert.
- **Lead-weighted research depth** allocates more research to high-value leads.
- **Iterative refinement loop** improves output quality through self-review.
- **Feedback loop** — campaign results feed back into goldset for continuous improvement.

## Conversion Impact Stack

The features stack on each other for compounding gains:

```
Base personalization          →  ~2-5% reply rate
  + Lead-weighted research     →  +30-50% (better evidence → better lines)
  + Send-time optimization     →  +20-40% (more opens)
  + Follow-up sequences        →  +2-3x total touchpoints
  + A/B testing                →  +10-30% (proven best angles)
  + Feedback loop              →  compounding over time
```

## Technical Highlights (For Developer/CTO Buyers)

- Runs locally — no data leaves your machine.
- No vendor lock-in — CSV/XLSX export, open-source LLM clients.
- 50+ LLM providers supported via OpenRouter, Gemini, DeepSeek, OpenAI.
- Reproducible — every row stores prompt hashes for auditability.
- Testable — frozen eval sets catch quality regressions before they ship.
- Extensible — Python codebase, well-documented module boundaries.