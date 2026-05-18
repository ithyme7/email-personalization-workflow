# Tool Budget Options For Scaling Personalization

This is a practical tool budget to discuss before scaling beyond test batches.

## Low Budget Baseline

Estimated monthly budget: **$50 to $150/month**

Use this if the goal is to run 100 to 500 prospects per week with human review.

- **LLM API budget:** $30 to $100/month
  - Use Gemini Flash/Flash-Lite for research extraction, classification, rewrite variants, and QC.
  - Keep budget circuit breakers on so a messy batch cannot burn spend unexpectedly.
- **Proxy/VPN budget:** $10 to $30/month
  - Useful for US-region App Store/browser checks where a client’s prospects mostly target the US.
  - The current region setting changes App Store country, locale, and timezone, but true IP-region testing needs a real proxy/VPN.
- **Storage/ops:** $0 to $20/month
  - Local-first workflow is enough for now.
  - Optional cloud storage only if screenshots or evidence packages need to be shared often.

Best for: early production, calibration batches, client-specific tone learning.

## Recommended Working Budget

Estimated monthly budget: **$150 to $400/month**

Use this if William wants the workflow to become reliable across multiple clients and 1,000+ prospects/month.

- **LLM API budget:** $100 to $250/month
  - Cheaper models for research/classification.
  - Stronger model only for final opener variants and strict QC where needed.
  - Enables 2 to 3 opener options per company without worrying about every test run.
- **Residential/geo proxy or VPN:** $30 to $100/month
  - Better for US app-store/review access and websites that alter content by region.
  - Reduces blocked/empty visual research rows.
- **App/review data fallback:** $20 to $100/month
  - Optional use of an app metadata/review provider if public scraping becomes unreliable.
  - Most useful for app-first campaigns where review complaints are the strongest personalization source.

Best for: recurring client work, multiple tone profiles, lower manual research time.

## Higher Quality / Scale Budget

Estimated monthly budget: **$400 to $1,000+/month**

Use this only if personalization becomes a serious delivery function, not just a side workflow.

- **Premium LLM for final copy/QC:** $200 to $500/month
  - Use Claude/GPT-style stronger models only for the final wording layer and judge layer.
  - Keep cheaper models for mechanical research.
- **Data enrichment/list-building tools:** $100 to $500+/month
  - Apollo, Clay, Phantombuster/Apify, Clearbit-style enrichment, or similar.
  - This would help with William’s separate bottleneck: list building quality.
- **More reliable app-review/data access:** $100 to $300/month
  - App Store / Google Play review APIs or data providers.
  - Reduces manual checking and region-specific gaps.

Best for: scaling personalization plus list building as a larger system.

## My Recommendation For The Next Call

Ask for a starting tool budget of **$150 to $250/month**.

That should be enough to:

- run larger test batches without worrying about API limits,
- test multiple models properly,
- use US-region proxy/VPN when needed,
- generate 2 to 3 options per company,
- keep stronger QC on every line,
- and start measuring which personalization angles actually get replies.

The biggest quality unlocks are:

1. **Enough API budget** to run multi-shot generation and QC without cutting corners.
2. **US-region proxy/VPN** for app-first campaigns.
3. **Review/app data fallback** if public App Store review scraping gets inconsistent.
4. **Optional enrichment/list-building tooling** if William wants help beyond personalization.

The workflow is still designed to stay human-in-the-loop. Extra budget should reduce manual research time and improve evidence quality, not remove review completely.
