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

## Retention

Recommended default:

- Keep source CSV and final output only as long as needed for delivery.
- Delete cache and screenshots after acceptance unless there is a clear reason to retain them.
- Keep sanitized examples for demos only when client-identifying information has been removed.
