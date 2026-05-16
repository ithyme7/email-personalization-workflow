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
python cli.py --input data/input/sample_companies.csv --output data/output/sample_output.xlsx --campaign-context "We help mobile app teams with this type of work, figure out where users drop off and why." --reuse-duplicate-personalization --client-batch-output
```

## Run A Real Batch

```bash
python cli.py --input path/to/leads.csv --output data/output/personalization_review.xlsx --campaign-context "Your campaign context here" --reuse-duplicate-personalization --client-batch-output
```

## Build A Windows EXE

```bash
pyinstaller EmailPersonalizer.spec --noconfirm
```

The compiled app will be created under `dist/`.

## Output Workbook

The Excel workbook includes:

- `Dashboard`: batch status, review workload, source coverage, visual confidence, friction types, and quality flags.
- `Review`: the main working tab with the personalized line, template preview, evidence, flags, and manual-review notes.
- `Research Details`: longer evidence, screenshots, source URLs, visual observations, and angle-gate notes.
- `Summary`: basic counts and usage notes.

## Limitations

- Automated visual review is useful for obvious issues, but low-confidence findings should be checked manually.
- App-store and public listing evidence is not the same as a real app walkthrough.
- LinkedIn should be added through manual notes or publicly accessible data you provide.
- Some websites block scraping or browser rendering.
- Final tone still benefits from human review, especially for high-value campaigns.

## Quality Philosophy

The system is optimized for verifiable, specific, human-reviewable personalization. A plain accurate line is better than a clever hallucinated one.
