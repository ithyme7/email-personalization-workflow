# ROADMAP.md

## Current Phase

Local/productized workflow for real outbound batches.

Not SaaS yet.

---

## Immediate Priorities

### 1. Product-quality delivery hygiene

- separate review export and delivery export
- exclude Edit/Reject from delivery
- flag mismatches
- clean client-safe export
- reduce noisy internal fields

### 2. Multi-shot quality

- ensure 2-3 options are meaningfully different
- score each option separately
- recommend only safe options
- save selected and non-selected options

### 3. Sales-principles refinement

- specificity beats cleverness
- signal -> implication -> tension
- low salesiness
- bridge into pitch
- no fake familiarity
- evidence before claim

### 4. App-first research

- improve Apple App Store extraction
- improve Google Play extraction
- stricter app/company matching
- prefer app/review evidence for app-first products

### 5. Runtime reliability

- provider 429 handling
- partial save on failure
- request/token/cost logging
- prompt caching
- fewer API calls
- browser worker fix

---

## Next Priorities

### Lead Process Automation

- lead quality scoring
- missing field detection
- domain cleanup
- duplicate handling
- email verification interface
- Apollo/Clay-friendly exports
- segmentation and ICP mapping

### Campaign Feedback Loop

- import opens/replies/booked calls
- match outcomes to opener/angle
- angle performance reports
- model/prompt version comparison
- client-specific learning

### Multi-Client Profiles

- separate client tone profiles
- separate goldsets
- separate export mappings
- client-specific sendability thresholds
- client-specific prompt versions
