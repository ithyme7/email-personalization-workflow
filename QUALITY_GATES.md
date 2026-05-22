# QUALITY_GATES.md

## Release Gate

Before a batch output is considered client-ready:

1. Delivery export contains only Send or human-approved rows.
2. No Reject rows in delivery.
3. No unresolved Edit rows in delivery.
4. Original input columns preserved.
5. No local paths.
6. No raw traces.
7. No unsupported claims.
8. No fake app usage.
9. No wrong-surface sendable rows.
10. No low-confidence traffic/funding/tech-stack based openers.

---

## Batch Health Metrics

Track per batch:

- total rows
- unique companies
- Send count
- Edit count
- Reject count
- no_sendable_option count
- wrong_surface count
- low_evidence count
- unsupported_claim count
- fake_familiarity count
- average line length
- source URL coverage
- app evidence coverage
- review evidence coverage
- API requests
- tokens
- cost
- runtime

---

## Acceptable Early Benchmarks

During calibration:

- Send rate may be low
- Edit rate may be high
- Reject rate is acceptable if QC is conservative

After calibration:

- Send should increase
- false sends should decrease
- wrong-surface rows should decrease
- heavy rewrites should decrease
- reviewer time per row should decrease

---

## Hard Fail Reasons

Use hard fail for:

- unsupported claim
- fake app usage
- wrong company/domain
- wrong product/app
- wrong surface with weak evidence
- hallucinated funding/traffic
- local path in client export
- raw trace in client export
- no evidence
- dangerous overclaim

---

## Soft Edit Reasons

Use soft edit for:

- too long
- slightly generic
- weak bridge
- wording too salesy
- evidence okay but copy weak
- tone mismatch
- needs softer claim
- useful angle but needs rewrite

---

## Final Delivery Gate

A row can enter delivery only if:

```text
sendability = Send
OR
human_decision = Send
OR
human_decision = Edit AND edited_final_opener exists
```

Otherwise exclude it.
