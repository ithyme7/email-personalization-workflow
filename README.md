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
11. Export a readable workbook with dashboard, review rows, evidence, sources, confidence, and manual-review notes.

The workflow is intentionally conservative: weak evidence should become a review flag, not a confident-sounding guess.

## Features

- CSV input validation.
- URL normalization and duplicate handling.
- Public website research with `requests` and `BeautifulSoup`.
- Optional Selenium browser fallback for JavaScript-heavy pages.
- Desktop and mobile screenshot-based visual review.
- Evidence-first prompt chain.
- Friction-prioritized angle selection.
- Strict no-em-dash and genericness checks.
- Manual-review mode so weak rows still export.
- CSV or Excel output.
- Dark-mode Excel dashboard with review, research, and summary tabs.
- Model provider support for Gemini, OpenRouter, DeepSeek, and OpenAI-style chat APIs.
- Tone profiles for different client styles and campaign types.
- Local Streamlit web app with CSV upload, campaign context, tone profile presets, custom prompt/profile builder, editable review rows, and CSV/XLSX export.

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

- CSV upload
- campaign context input
- provider/model/API-key settings
- 50 tone presets
- custom prompt/profile creation
- run batch button
- review/edit rows
- export edited CSV
- export edited XLSX
- export full workbook

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

## Build A Windows EXE

```bash
pyinstaller EmailPersonalizer.spec --noconfirm
```

The compiled app will be created under `dist/`.

## Output Workbook

The Excel workbook includes:

- `Dashboard`: batch status, review workload, source coverage, visual confidence, friction types, and quality flags.
- `Review`: the main working tab with the personalized line, template preview, evidence, flags, and manual-review notes.
- `Research Details`: longer evidence, screenshots, source URLs, visual observations, angle-gate notes, tone profile, and model metadata.
- `Summary`: basic counts and usage notes.

## Productized Service Workflow

For client work, the recommended workflow is:

1. Ask for the lead list, campaign context, target persona, and 3 to 5 examples of good/bad personalization.
2. Create or select the closest tone profile.
3. Run a small calibration batch of 10 to 25 leads.
4. Review weak rows manually, especially app-first companies and low-confidence visual findings.
5. Ask the client to mark 5 good lines and 5 off-tone lines.
6. Tune the tone profile before scaling to larger batches.

Useful internal docs:

- `docs/OPERATING_SOP.md`
- `docs/GO_TO_MARKET.md`
- `docs/SECURITY_PRIVACY.md`
- `docs/QUALITY_BENCHMARK.md`
- `docs/DEMO_SCRIPT.md`
- `docs/WEB_APP_USAGE_NL.md`

## Limitations

- Automated visual review is useful for obvious issues, but low-confidence findings should be checked manually.
- App-store and public listing evidence is not the same as a real app walkthrough.
- LinkedIn should be added through manual notes or publicly accessible data you provide.
- Some websites block scraping or browser rendering.
- Final tone still benefits from human review, especially for high-value campaigns.

## Quality Philosophy

The system is optimized for verifiable, specific, human-reviewable personalization. A plain accurate line is better than a clever hallucinated one.
