# Security And Privacy

## Data Handling

Do not commit or share:

- client lead lists
- generated outputs
- scraped cache files
- screenshots
- `.env` files
- API keys
- private notes

Generated data should live under `data/output/`, `data/cache/`, and `data/screenshots/`, which are ignored by git.

## API Keys

Keys should be loaded from `.env` or entered locally at runtime. They should never be pasted into screenshots, chats, GitHub issues, logs, or committed files.

If a key is exposed, rotate it immediately.

## Client Workspaces

For paid work, use one workspace/folder per client when possible. Clear cache and screenshots after delivery if the client does not need them retained.

## LinkedIn And Account-Based Research

Use only reviewer-supplied notes or publicly accessible information. Do not bypass login walls or scrape private account data.

## Output Review

Every output is reviewable. The workflow should mark uncertain rows rather than hiding uncertainty.

## Internal Versus Client-Safe Artifacts

Internal artifacts can include rich debugging material such as:

- Playwright traces
- raw detector findings
- raw axe/Lighthouse details
- local screenshot paths
- internal reviewer notes

Do not treat those as the default client deliverable.

For external handoff, use the web app's client-safe package. It keeps the client-facing CSV/XLSX lightweight and removes raw traces, internal detector output, local filesystem paths, and low-level audit details. It may include selected screenshots when those screenshots are useful evidence.

If a row has `privacy_flags`, review it before sharing any related assets.

Client-safe packages now include a `manifest.json` with:

- package timestamp
- number of input and delivered rows
- row filter policy
- excluded artifact classes
- privacy sanitizers used
- remaining privacy scan flags

Package creation is blocked if hard leaks remain after sanitizing, such as local filesystem paths, API-key-like values, signed/tokenized URL parameters, or trace ZIP references.

Screenshots are privacy-scanned before inclusion. By default `REQUIRE_SCREENSHOT_OCR=true`, so screenshot text must be scanned for emails, phone numbers, key-like strings, local paths, and tokenized URLs before a screenshot can be included.

If OCR is unavailable while `REQUIRE_SCREENSHOT_OCR=true`, screenshots are skipped rather than included blindly, and the reason is recorded in `screenshot_privacy_notes`. To verify local OCR support, run:

```bash
python tools/check_ocr.py
```

Only set `REQUIRE_SCREENSHOT_OCR=false` for local/internal debugging where screenshots will not be shared externally.

Playwright traces are internal debugging artifacts. By default, traces are only retained for flagged/failing browser checks. Set `PLAYWRIGHT_TRACES=always` only when debugging locally.

## Retention

Recommended default:

- Keep source CSV and final output only as long as needed for delivery.
- Delete cache and screenshots after acceptance unless there is a clear reason to retain them.
- Keep sanitized examples for demos only when client-identifying information has been removed.
