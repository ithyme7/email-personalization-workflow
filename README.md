# Email Personalization Workflow

A local Python workflow for turning a lead CSV into a reviewable Excel workbook with researched cold-email personalization notes — including follow-up sequences, A/B testing, and send-time optimization.

The tool is designed around evidence first, copy second:

1. Import and validate a lead CSV.
2. Deduplicate company rows when requested.
3. Research public website pages.
4. Fall back to Playwright browser rendering for JavaScript-heavy pages.
5. Collect public app-store/listing signals when available.
6. Run visual checks on desktop and mobile screenshots.
7. Extract structured evidence.
8. Select the strongest friction-first angle.
9. Generate one short opening line and one insight.
10. Run strict quality control with an iterative refinement loop.
11. Run a sendability gate that separates rows into Send, Edit, or Reject.
12. Optimize send-time per lead (timezone + historical open-rate data).
13. Optionally generate multi-touch follow-up sequences (Value → Social Proof → Direct Ask → Breakup).
14. Optionally run A/B experiments with Thompson Sampling allocation and chi-squared significance testing.
15. Export a readable workbook with dashboard, review rows, evidence, sources, confidence, and manual-review notes.

The workflow is intentionally conservative: weak evidence should become a review flag, not a confident-sounding guess.

## Features

### Research & Evidence

- CSV input validation with deduplication.
- URL normalization and duplicate handling.
- Public website research with `requests` and `BeautifulSoup`.
- Optional Playwright browser fallback for JavaScript-heavy pages.
- Desktop and mobile screenshot-based visual review.
- App-first routing: when a mobile app is detected, app/onboarding evidence is prioritized over blog or generic website observations.
- Product-surface classification for app-first products, website-first leadgen, B2B services, commerce pages, and marketplace/booking flows.
- Optional Playwright checks for full-page desktop/mobile screenshots, selective trace files, visible CTA checks, and dead-link candidates.
- Browser retry/backoff settings plus optional proxy and user-agent configuration for fragile or rate-limited sites.
- Optional Lighthouse checks for mobile quality signals when enabled.
- Local axe-core accessibility checks through the browser context for high-confidence accessibility/CTA issues.
- Shareable screenshot assets copied next to the workbook and zipped into a delivery package. Raw traces stay internal.
- Lead-weighted research depth scoring — enterprise leads get deeper research, simple leads get minimal research.

### Prompt Chain & Quality Control

- Evidence-first prompt chain: research feeds angle selection, angle feeds writing, writing feeds QC.
- Friction-prioritized angle selection from a taxonomy of angles.
- Iterative refinement loop: the model can revise its own output based on QC feedback (configurable `max_refinement_iterations`).
- Quality checker with temperature=0.4 for balanced rewrite suggestions.
- Personalization writer with temperature=0.6 for creative, diverse copy.
- Evidence extractor with temperature=0.1 for deterministic fact retrieval.
- Strict no-em-dash and genericness checks.
- Sentiment mismatch detection between evidence tone and copy tone.
- Manual-review mode so weak rows still export.
- System/user prompt split for cache efficiency (Fix #5).

### Sendability Gate

- Multidimensional gate with hard-fail reasons, soft-edit reasons, evidence score, copy score, outcome score, template-fit score, visual reliability, and surface correctness.
- Grounding checks flag lines that are not lexical traceable to extracted evidence.
- Deliverability checks flag spam-trigger wording and accidental HTML.
- Budget checks stop API usage before a configured cost/call limit is exceeded.
- Human edit/goldset workflow with reviewed examples, frozen eval examples, and candidate training examples.

### Output & Export

- CSV or Excel output.
- Dark-mode Excel workbook with dashboard, review, research details, and summary tabs.
- Client delivery export with a smaller column set for handoff.
- Native CSV/XLSX export mappings for Generic, Lemlist, Instantly, and Smartlead imports.
- Client-safe ZIP package with manifest, screenshot privacy scan hooks, and stricter redaction/blocking for sensitive values.
- Schema-first row provenance using Pydantic-backed canonical rows.
- Prompt and tone-profile hashes stored on generated rows and run history for traceability.

### Send-Time Optimization

- Per-lead optimal send-time calculation based on timezone and historical open-rate data.
- 12 timezone-region presets with research-backed optimal hours.
- Falls back to generic best-practice windows when no historical data is available.
- Activated via `SEND_TIME_OPTIMIZATION_ENABLED=true`.

### Follow-Up Sequence Engine

- Multi-touch follow-up email generation for leads that did not convert on the first attempt.
- 4-step strategy per lead: **Value** → **Social Proof** → **Direct Ask** → **Breakup**.
- Angle deduplication: sequences avoid reusing the same angle as the original email.
- Generic language detection: flags "just checking in", "bumping this", etc.
- Per-step quality scoring; steps below threshold are marked `needs_review`.
- Only runs for leads with `send_confidence == "send"` and `research_depth >= 0.6`.
- Activated via `FOLLOW_UP_SEQUENCE_ENABLED=true`.

### A/B Testing Framework

- Experiment registration with named variants and traffic allocation ratios.
- Deterministic lead-to-variant assignment via MD5 hashing (same lead always gets the same variant).
- Thompson Sampling bandit for adaptive traffic allocation as results come in.
- Chi-squared significance testing with configurable significance level (default 0.05).
- Wilson score confidence intervals per variant.
- Automatic win/loss detection with early stopping recommendations.
- Activated via `AB_TESTING_ENABLED=true`.

### LLM Support

- Model provider support for Gemini, OpenRouter, DeepSeek, and OpenAI-style chat APIs.
- Per-call temperature configuration:
  - Evidence extraction: 0.1 (deterministic)
  - Quality checker: 0.4 (balanced)
  - Personalization writer: 0.6 (creative)
- TTL-based prompt/response cache to avoid redundant API calls.
- Rate limiting with configurable tokens and cooldown.
- Optional LLM cost/call circuit breaker with `MAX_BATCH_COST_USD` and `MAX_LLM_CALLS_PER_BATCH`.

### Tone Profiles

- 50+ built-in tone presets accessible via a local library JSON file.
- Custom client-specific tone profiles stored as JSON in `tone_profiles/`.
- Tone calibration from client feedback in the web app.

### Web App (Streamlit)

- CSV upload, Google Sheets input, or demo sample mode.
- Campaign context input.
- Provider/model/API-key settings in sidebar.
- Pre-flight system check button.
- Row-level progress bar with background batch execution.
- Dashboard with sendability split, review workload, visual confidence, friction types, quality flags, and estimated model cost.
- Sendability dashboard showing Send/Edit/Reject split with hard-fail and soft-edit reasons.
- Focused review panel with evidence, source links, email preview side by side.
- Human review fields for final decision, edited line, edit reason, and notes.
- Evals tab for frozen goldset agreement, send precision, false sends, and eval report export.
- Client Training tab for exporting a feedback template and importing completed feedback.
- Batch history with run date, model, cost estimate, ready/review split, and output path.
- Tone calibration from client feedback.
- Export as CSV, XLSX, full workbook, client delivery export, or sending-tool import (Generic, Lemlist, Instantly, Smartlead).
- Client-safe ZIP package for external handoff.
- Optional Google Sheets export.

### CLI

```bash
python cli.py --input data/input/leads.csv \
  --output data/output/review.xlsx \
  --campaign-context "We help SaaS teams reduce churn" \
  --tone-profile friction_first \
  --reuse-duplicate-personalization \
  --client-batch-output
```

Interactive menu (`personalizer_app.py`) with:
- New personalization run
- Feedback entry (open/reply/conversion results)
- Feedback dashboard
- Send-time advice viewer
- A/B test dashboard
- Sequence overview

### Eval & Release

- Frozen eval runner for regression testing locked examples.
- Judge bakeoff for comparing LLM judge models against the same goldset.
- CI checks with synthetic frozen-eval fixture, manifest checksum, privacy tests, and guardrail tests.
- Release gate CLI for enforcing eval thresholds before treating a version as production-ready.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy the environment example:

```bash
copy .env.example .env
```

Then add one API key to `.env`.

**Gemini example:**
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
MODEL_NAME=gemini-3.1-flash-lite
TONE_PROFILE=friction_first
```

**OpenRouter example:**
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here
MODEL_NAME=openai/gpt-4o-mini
```

If no API key is set, the tool still validates input and exports research/review output, but it will not generate new AI-written lines.

## Optional Settings

All optional. Defaults are sensible for most use cases.

| Variable | Default | Description |
|---|---|---|
| `PERSONALIZATION_OPTIONS` | 3 | Number of opener options per lead (max 3) |
| `RESEARCH_REGION` | `us` | Apple review country + browser locale hints |
| `APP_STORE_COUNTRY` | `us` | App Store country for review scraping |
| `BROWSER_LOCALE` | `en-US` | Browser locale for page rendering |
| `BROWSER_TIMEZONE` | `America/New_York` | Browser timezone for page rendering |
| `BROWSER_RETRY_ATTEMPTS` | 3 | Retries for browser page loads |
| `BROWSER_PROXY_URL` | _(empty)_ | Optional proxy for browser requests |
| `BROWSER_USER_AGENT` | _(empty)_ | Optional custom user-agent |
| `MAX_BATCH_COST_USD` | 0 (disabled) | Budget guardrail — stops batch if exceeded |
| `MAX_LLM_CALLS_PER_BATCH` | 0 (disabled) | Call-count guardrail — stops batch if exceeded |
| `CACHE_TTL_SECONDS` | _(see config)_ | How long to reuse LLM responses for identical prompts |
| `MAX_REFINEMENT_ITERATIONS` | 3 | Max self-revision loops per personalization line |
| `SEND_TIME_OPTIMIZATION_ENABLED` | `false` | Enable per-lead send-time calculation |
| `SEND_TIME_OPTIMIZATION_HOURS_AHEAD` | 24 | How far ahead to schedule (in hours) |
| `FOLLOW_UP_SEQUENCE_ENABLED` | `false` | Enable multi-touch follow-up sequence generation |
| `FOLLOW_UP_MAX_STEPS` | 4 | Max follow-up steps per sequence |
| `FOLLOW_UP_MIN_QUALITY_SCORE` | 6.0 | Minimum quality score to include a sequence step |
| `AB_TESTING_ENABLED` | `false` | Enable A/B experiment traffic splitting |
| `AB_EXPERIMENT_ID` | `default` | Experiment identifier for tracking |
| `AB_EXPLORATION_RATE` | 0.1 | Fraction of traffic to explore (epsilon-greedy) |
| `AB_INITIAL_TRAFFIC_FRACTION` | 0.5 | Starting traffic split per variant |
| `AB_SIGNIFICANCE_LEVEL` | 0.05 | p-value threshold for significance |
| `AB_MIN_SAMPLE_SIZE` | 100 | Minimum samples per variant before analysis |
| `AB_MAX_TOTAL_LEADS` | 10000 | Hard cap per experiment |

## Pre-flight Check

Before a large batch:

```bash
python cli.py --input data/input/sample_companies.csv --output data/output/preflight.xlsx --preflight-only
```

This checks output folder, SQLite history, proxy config, API access, screenshot OCR readiness, and Playwright/axe browser detectors. Missing API keys are reported clearly but do not stop research-only mode.

## Run The Sample

```bash
python cli.py --input data/input/sample_companies.csv \
  --output data/output/sample_output.xlsx \
  --campaign-context "We help mobile app teams with this type of work, figure out where users drop off and why." \
  --reuse-duplicate-personalization \
  --client-batch-output \
  --tone-profile friction_first
```

## Run The Web App

```bash
streamlit run web_app.py
```

Then open `http://localhost:8501`.

Double-click `Start_Email_Personalizer_Web_App.bat` on Windows (waits for Streamlit and auto-opens browser).

## Run A Real Batch

```bash
python cli.py --input path/to/leads.csv \
  --output data/output/personalization_review.xlsx \
  --campaign-context "Your campaign context here" \
  --reuse-duplicate-personalization \
  --client-batch-output \
  --tone-profile friction_first
```

Optional sending-tool export:

```bash
python cli.py --input path/to/leads.csv \
  --output data/output/personalization_review.xlsx \
  --campaign-context "Your campaign context here" \
  --reuse-duplicate-personalization \
  --client-batch-output \
  --tone-profile friction_first \
  --sending-tool-preset lemlist \
  --sending-tool-output data/output/lemlist_import.csv
```

## Tone Profiles

Profiles live in `tone_profiles/` and are selected with `--tone-profile`.

- 50+ presets available in the web app and through the tone preset library.
- `friction_first`: short conversational lines focused on a current UX/conversion friction point.
- `proof_led_b2b`: stronger emphasis on weak proof, trust leaks, case studies, and demo conversion.
- `founder_casual`: warmer founder-to-founder style while staying evidence-led.

Add a new client profile by copying one JSON file and adjusting the opening style, banned phrases, QC focus, and examples.

## Output Workbook

| Tab | Contents |
|---|---|
| Dashboard | Sendability split, surface correctness, batch status, review workload, source coverage, visual confidence, friction types, review reasons |
| Review | Main working tab with sendability decision, hard/soft reasons, surface correctness, personalized line, template preview, evidence, shareable screenshots, flags, manual-review notes |
| Research Details | Longer evidence, screenshots, source URLs, visual observations, internal UX validator findings, angle-gate notes, tone profile, model metadata |
| Summary | Basic counts and usage notes |

### Row-Level Provenance

Every generated row includes:

- `prompt_set_hash` — identifies the exact prompt version used
- `evidence_prompt_hash` — evidence extraction prompt version
- `write_prompt_hash` — personalization writer prompt version
- `qc_prompt_hash` — quality checker prompt version
- `tone_profile_hash` — tone profile version

These hashes make it possible to compare campaign outcomes against the exact prompt/profile version that generated each line.

### New Columns (Fixes #12–#14)

When the relevant settings are enabled, additional columns appear:

| Column | Source | Description |
|---|---|---|
| `sequence_step` | Sequence Engine | Which step in the follow-up sequence (1–4) |
| `follow_up_type` | Sequence Engine | Strategy type: `value_add`, `social_proof`, `direct_ask`, `breakup` |
| `sequence_opening_line` | Sequence Engine | Generated opening line for this follow-up step |
| `sequence_body_text` | Sequence Engine | Generated body text for this follow-up step |
| `sequence_cta_text` | Sequence Engine | Generated call-to-action for this follow-up step |
| `ab_experiment_id` | A/B Testing | Experiment identifier |
| `ab_variant_id` | A/B Testing | Assigned variant number |
| `ab_variant_label` | A/B Testing | Human-readable variant label |
| `ab_testing_enabled` | A/B Testing | Whether A/B testing was active for this run |
| `suggested_send_time_utc` | Send-Time Optimizer | Recommended UTC timestamp |
| `suggested_send_timezone` | Send-Time Optimizer | Detected or assigned timezone |
| `send_time_confidence` | Send-Time Optimizer | Confidence score (0–1) |
| `send_time_source` | Send-Time Optimizer | Source: `historical`, `regional`, or `generic` |

---

## Frozen Eval Runner

Once you have reviewed rows saved to `data/goldset/frozen_eval_set.csv`:

```bash
python eval_runner.py
```

The eval report measures:

- Gate vs. human agreement
- Send precision
- Reject recall
- False-send rows
- Surface-correctness rate
- Average evidence and template-fit scores

Enforce the release gate:

```bash
python eval_runner.py --enforce-gate --fail-on-regression
```

Write a new baseline:

```bash
python eval_runner.py --write-baseline
```

Run a judge bakeoff:

```bash
python judge_bakeoff.py --models "gemini-3.1-flash-lite,gemini-2.5-flash"
```

## Client Training Template

The web app's `Client Training` tab exports a simple feedback form where the client marks each line as:

- `Send as is` — the line is good to go
- `Rewrite` — the line had the right idea but needs rewriting
- `Reject` — the line should not be sent

Completed feedback is imported back into the goldset (reviewed_examples or candidate_training_set). The same tab supports post-send campaign results for tracking opens, replies, bookings, and bounces.

## Productized Service Workflow

1. Ask for the lead list, campaign context, target persona, and 3–5 good/bad examples.
2. Create or select the closest tone profile.
3. Run a calibration batch of 10–25 leads.
4. Review weak rows manually.
5. Use the sendability gate to separate into Send, Edit, Reject.
6. Check hard-fail reasons separately from soft-edit reasons.
7. Check surface correctness.
8. Mark reviewed rows with a human decision and edit reason.
9. Save to the right goldset split.
10. Ask the client to mark 5 good and 5 off-tone lines.
11. Tune the tone profile before scaling.

## Public Safety Notes

This repository contains only generic source code, prompts, and fake sample data. Do not commit real client lists, generated outputs, API keys, browser screenshots, cache files, or `.env` files.

## Build A Windows EXE

```bash
pyinstaller EmailPersonalizer.spec --noconfirm
```

## Useful Docs

- `docs/GO_TO_MARKET.md` — positioning, pricing, sales flow
- `docs/OPERATING_SOP.md` — day-to-day operations guide
- `docs/QUALITY_BENCHMARK.md` — quality benchmarks and targets
- `docs/GOLDSET_EVALS.md` — frozen eval methodology
- `docs/CLIENT_TRAINING_GUIDE.md` — training clients to give feedback
- `docs/DEMO_SCRIPT.md` — demo call script
- `docs/WEB_APP_USAGE_NL.md` — Dutch webapp walkthrough
- `docs/SECURITY_PRIVACY.md` — security and privacy practices

## Limitations

- Automated visual review catches obvious issues; low-confidence findings should be checked manually.
- Internal UX validators flag contrast, tap targets, overflow, broken links, Lighthouse/axe issues, but the final email copy should translate those into natural observations.
- App-store and public listing evidence is not the same as a real app walkthrough.
- LinkedIn data should be added through manual notes or publicly accessible data.
- Some websites block scraping or browser rendering.
- Final tone still benefits from human review, especially for high-value campaigns.
- Follow-up sequences and A/B testing are opt-in (disabled by default) and require feedback data to become increasingly effective.

## Quality Philosophy

The system is optimized for verifiable, specific, human-reviewable personalization. A plain accurate line is better than a clever hallucinated one.