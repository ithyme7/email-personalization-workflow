# Email Personalization Workflow

A local Python workflow for turning a lead CSV into a reviewable Excel workbook with researched cold-email personalization notes.

The tool is designed around evidence first, copy second:

1. Import and validate a lead CSV.
2. Deduplicate company rows when requested.
3. Research public website pages.
4. Fall back to browser rendering for JavaScript-heavy pages.
5. Collect public app-store/listing signals when available.
6. Run visual checks on desktop and mobile screenshots.
7. Extract structured evidence.
8. Select the strongest friction-first angle.
9. Generate one short opening line and one insight.
10. Run strict quality control.
11. Run a sendability gate that separates rows into Send, Edit, or Reject.
12. Export a readable workbook with dashboard, review rows, evidence, sources, confidence, and manual-review notes.

The workflow is intentionally conservative: weak evidence should become a review flag, not a confident-sounding guess.

## Features

- CSV input validation.
- URL normalization and duplicate handling.
- Public website research with `requests` and `BeautifulSoup`.
- Optional Selenium browser fallback for JavaScript-heavy pages.
- Desktop and mobile screenshot-based visual review.
- App-first routing: when a mobile app is detected, app/onboarding evidence is prioritized over blog or generic website observations.
- Product-surface classification for app-first products, website-first leadgen, B2B services, commerce pages, and marketplace/booking flows.
- Optional Playwright checks for full-page desktop/mobile screenshots, trace files, visible CTA checks, and dead-link candidates.
- Optional Lighthouse checks for mobile quality signals when enabled.
- axe-core accessibility checks through the browser context for high-confidence accessibility/CTA issues.
- Shareable screenshot/trace assets copied next to the workbook and zipped into a delivery package.
- Evidence-first prompt chain.
- Friction-prioritized angle selection.
- Strict no-em-dash and genericness checks.
- Manual-review mode so weak rows still export.
- CSV or Excel output.
- Dark-mode Excel dashboard with review, research, and summary tabs.
- Model provider support for Gemini, OpenRouter, DeepSeek, and OpenAI-style chat APIs.
- Tone profiles for different client styles and campaign types.
- Local Streamlit web app with CSV upload, campaign context, tone profile presets, custom prompt/profile builder, editable review rows, and CSV/XLSX export.
- Accurate row-level progress bar in the web app.
- Optional Google Sheets input and Google Sheets export.
- Batch cost estimate using editable model-price assumptions.
- Optional client-specific tone profiles saved locally.
- One-click Windows launcher for the web app.
- Demo sample mode for low-risk walkthroughs during calls.
- Batch history with run date, model, cost estimate, ready/review split, and output path.
- Tone calibration tab for saving client feedback as a reusable profile.
- Multidimensional sendability gate with hard-fail reasons, soft-edit reasons, evidence score, copy score, outcome score, template-fit score, visual reliability, and surface correctness.
- Viewport scope and evidence scope for visual/UX claims.
- Human edit/goldset workflow with reviewed examples, frozen eval examples, and candidate training examples.
- Frozen eval runner for measuring gate/human agreement on locked examples.
- Client delivery export with a smaller column set for handoff.
- Client-safe delivery package that excludes raw traces, internal detector output, and local paths.

## Public Safety Notes

This repository contains only generic source code, prompts, and fake sample data. Do not commit real client lists, generated outputs, API keys, browser screenshots, cache files, or `.env` files.

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

Gemini example:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
MODEL_NAME=gemini-3.1-flash-lite
TONE_PROFILE=friction_first
```

OpenRouter example:

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here
MODEL_NAME=openai/gpt-4o-mini
```

If no API key is set, the tool still validates input and exports research/review output, but it will not generate new AI-written lines.

## CSV Format

Required columns:

- `company_name`
- `website_url`

Optional columns:

- `linkedin_url`
- `recipient_name`
- `recipient_role`
- `campaign_context`
- `optional_notes`
- `linkedin_observation`
- `linkedin_source_note`
- `app_store_url`
- `app_flow_observation`
- `app_flow_source_note`
- `screenshot_url`
- `recent_news_url`
- `recent_news_note`
- `competitor_context`

## Run The Sample

```bash
python cli.py --input data/input/sample_companies.csv --output data/output/sample_output.xlsx --campaign-context "We help mobile app teams with this type of work, figure out where users drop off and why." --reuse-duplicate-personalization --client-batch-output --tone-profile friction_first
```

## Run The Web App

```bash
streamlit run web_app.py
```

Then open:

```text
http://localhost:8501
```

The web app supports:

- demo sample mode
- CSV upload
- Google Sheets input
- campaign context input
- provider/model/API-key settings
- 50 tone presets
- optional client-specific custom prompt/profile creation
- run batch button
- row-level progress bar
- dashboard with review workload, visual confidence, friction types, quality flags, and estimated model cost
- sendability dashboard showing Send/Edit/Reject split, hard-fail reasons, soft-edit reasons, and surface correctness
- Evals tab for frozen goldset agreement, send precision, false sends, and eval report export
- batch history
- tone calibration from client feedback
- review/edit rows
- human review fields for final decision, edited line, edit reason, and notes
- export edited CSV
- export edited XLSX
- export full workbook
- optional export to Google Sheets
- simplified client delivery CSV/XLSX
- client-safe ZIP package for external handoff

On Windows you can also double-click:

```text
Start_Email_Personalizer_Web_App.bat
```

The launcher waits until Streamlit is ready, opens the browser, and uses the next free localhost port if `8501` is already in use.

## Run A Real Batch

```bash
python cli.py --input path/to/leads.csv --output data/output/personalization_review.xlsx --campaign-context "Your campaign context here" --reuse-duplicate-personalization --client-batch-output --tone-profile friction_first
```

## Tone Profiles

Tone profiles live in `tone_profiles/` and can be selected with `--tone-profile`.

Built-in profiles:

- 50 presets are available in the web app and through the tone preset library.
- `friction_first`: short conversational lines focused on a current UX/conversion friction point.
- `proof_led_b2b`: stronger emphasis on weak proof, trust leaks, case studies, and demo conversion.
- `founder_casual`: warmer founder-to-founder style while staying evidence-led.

You can add a new client profile by copying one JSON file and changing the opening style, banned phrases, QC focus, and examples.

The web app can also save optional client-specific profiles under `data/custom_tone_profiles/`. You do not have to use this for every run; it is mainly useful when a client gives repeatable tone feedback.

## Build A Windows EXE

```bash
pyinstaller EmailPersonalizer.spec --noconfirm
```

The compiled app will be created under `dist/`.

## Output Workbook

The Excel workbook includes:

- `Dashboard`: sendability split, surface correctness, batch status, review workload, source coverage, visual confidence, friction types, and review reasons.
- `Review`: the main working tab with sendability decision, hard/soft reasons, surface correctness, personalized line, template preview, evidence, shareable screenshots, flags, and manual-review notes.
- `Research Details`: longer evidence, screenshots, source URLs, visual observations, internal UX validator findings, angle-gate notes, tone profile, and model metadata.
- `Summary`: basic counts and usage notes.

When screenshots or traces are created, the exporter also creates:

- `<output_name>_assets/`
- `<output_name>_delivery_package.zip`

Use the zip when sharing visual evidence with someone else, because local paths such as `C:\Users\...` are only useful on the machine that generated the run.

For external delivery, prefer the client-safe package from the web app. It includes a cleaned CSV/XLSX and selected screenshots only. It excludes trace files, raw detector output, internal audit details, and local filesystem paths.

## Frozen Eval Runner

Once you have reviewed rows saved to `data/goldset/frozen_eval_set.csv`, you can export a regression report:

```bash
python eval_runner.py
```

The eval report measures:

- exact gate/human agreement
- send precision
- reject recall
- false-send rows
- surface-correctness rate
- average evidence and template-fit scores

Use this before changing prompts, thresholds, model choice, or tone profiles.

## Productized Service Workflow

For client work, the recommended workflow is:

1. Ask for the lead list, campaign context, target persona, and 3 to 5 examples of good/bad personalization.
2. Create or select the closest tone profile.
3. Run a small calibration batch of 10 to 25 leads.
4. Review weak rows manually, especially app-first companies and low-confidence visual findings.
5. Use the sendability gate to separate rows into Send, Edit, and Reject.
6. Check hard-fail reasons separately from soft-edit reasons.
7. Check surface correctness, especially for app-first companies.
8. Mark reviewed rows with a human decision and an edit reason.
9. Save the reviewed rows to the right goldset split.
10. Ask the client to mark 5 good lines and 5 off-tone lines.
11. Tune the tone profile before scaling to larger batches.

## Sendability And Goldset

The sendability layer is stricter than the normal row status. A row can have a generated line and still be marked `Edit` or `Reject` if it has weak evidence, possible unsupported claims, generic wording, technical audit language, low visual confidence, a missing outcome tie, poor template flow, or the wrong research surface.

Decisions:

- `Send`: can be considered for client delivery.
- `Edit`: promising, but needs a human pass before sending.
- `Reject`: do not send yet; evidence or copy is not reliable enough.

The gate is multidimensional:

- `hard_fail_reasons`: evidence or safety problems that should block sending.
- `soft_edit_reasons`: tone, length, flow, or confidence issues that can usually be fixed.
- `evidence_score`: source and evidence sufficiency.
- `copy_quality_score`: wording, length, genericness, and banned phrasing.
- `outcome_alignment_score`: connection to activation, conversion, retention, bookings, signup completion, or drop-off.
- `template_fit_score`: whether the line naturally flows into the campaign template.
- `surface_correctness`: whether the selected surface matches the product type.
- `visual_reliability_score`: how reliable the visual/UX finding is.
- `viewport_scope`: whether a visual claim is backed by mobile, desktop, both, or unknown viewport evidence.
- `evidence_scope`: whether the row has source URLs, screenshots, both, or thin evidence.
- `privacy_flags`: internal markers such as trace files or local paths that should not go into client handoff.

In the web app, use `human_decision`, `edited_line`, `edit_reason_category`, and `edit_notes` in the Review tab. Click `Save reviewed rows to goldset` to append reviewed examples to one of three local splits:

```text
data/goldset/reviewed_examples.csv
data/goldset/frozen_eval_set.csv
data/goldset/candidate_training_set.csv
```

- `reviewed_examples`: normal reviewed rows and client feedback.
- `frozen_eval_set`: locked regression examples used to compare prompts/models over time.
- `candidate_training_set`: examples that may later be useful for fine-tuning or preference tuning.

These files become the reusable learning set for tone calibration, prompt tuning, model comparison, and future pairwise evaluation.

Useful internal docs:

- `docs/OPERATING_SOP.md`
- `docs/GO_TO_MARKET.md`
- `docs/SECURITY_PRIVACY.md`
- `docs/QUALITY_BENCHMARK.md`
- `docs/GOLDSET_EVALS.md`
- `docs/DEMO_SCRIPT.md`
- `docs/WEB_APP_USAGE_NL.md`

## Limitations

- Automated visual review is useful for obvious issues, but low-confidence findings should be checked manually.
- Internal UX validators can flag contrast, tap target, overflow, broken-link, Lighthouse, or axe-core issues, but the final email copy should translate those into natural human observations.
- App-store and public listing evidence is not the same as a real app walkthrough.
- LinkedIn should be added through manual notes or publicly accessible data you provide.
- Some websites block scraping or browser rendering.
- Final tone still benefits from human review, especially for high-value campaigns.

## Quality Philosophy

The system is optimized for verifiable, specific, human-reviewable personalization. A plain accurate line is better than a clever hallucinated one.
