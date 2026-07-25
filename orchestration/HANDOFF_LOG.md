# Accepted Handoffs

## 2026-06-30 — Wave 1

- `W1-BASELINE-AUDIT`: accepted after inspecting `docs/multicity/00_baseline_audit.md` and independently rerunning 26/26 `unittest` tests. Audit is complete; Bengaluru numeric fixture is explicitly withheld because H3/TAM artifacts fail reconciliation.
- `W1-SOURCE-MAP`: accepted as a completed discovery/inventory task. Only Bengaluru local mappings are evidenced; all unfinished-city mappings remain unknown. Safety blockers B-004 and B-005 prohibit running the current UDISE/99acres variants.
- `W1-DOCS-SKELETON`: accepted after checking all four documents for unsupported completion/count claims. They remain clearly labeled skeletons/TODO where evidence is unavailable.

Wave 1 evidence changed the critical path: security/compliance remediation and a single-manifest Bengaluru reconciliation must precede production city collection and golden-fixture admission.

## 2026-06-30 — Wave 2 first QA cycle

- Contracts/config producer: implementation handoff received; independent QA passed schemas/config/IDs/path guards/ranking behavior.
- Safe collectors producer: returned for remediation after QA found critical contract-incompatible entity IDs and a high-severity path traversal issue.
- Bengaluru staging rebuild: deterministic/reconciled producer evidence confirmed by QA, but remains `BUILT_NOT_ADMITTED`; countable TAM semantics require method-owner review.
- Independent QA verdict: FAIL. Evidence: `audits/wave2/QA_REPORT.md` and `qa_results.json`.
- Integration security action: removed the literal Google Maps key fallback from `src/server.py` and added the variable name only to `.env.example`. External key rotation/revocation remains owner action under B-006.

## 2026-06-30 — Wave 2 remediation QA

- Collector owner corrected entity contracts/lineage and path containment. Orchestrator reran 8 collector, 10 contract/ranking, 2 reconciliation, and 26 legacy tests successfully with the repository's available runtimes.
- Fresh independent QA R1: PASS. Five of five typed/common fixtures validate, 12/12 hostile paths block, 40/40 null mappings fail closed, secret/OCR scan is clean, and Bengaluru staging hashes/reconciliation are unchanged. Evidence: `audits/wave2/QA_REPORT_R1.md`, `qa_results_r1.json`.
- Bounded Wave 2 framework is accepted. This does not admit Bengaluru staging, authorize production collection, verify source mappings, or prove provider-side key rotation.

## 2026-06-30 — Scope revision and QA cycles

- Added Ezyschooling page→detail collector, canonical merge/matching and runtime-only Google geocoding cache. Two remediation cycles closed canonical ID/schema, failure quarantine, and cache TTL/redaction defects. Code/data QA PASS; live collection remains blocked by B-008.
- Replaced 99acres Localities with a two-stage MagicBricks Localities collector. Three QA cycles found and closed contract, accounting, URL/path traversal, resumed-state quarantine, and evidence-authenticity defects. Final independent QA PASS. Five NCR components (IDs 2624, 6403, 2951, 6146, 2944) passed 100/100 bounded listing matches and 5/5 detail evidence. Technically ready for serialized production, still held behind the city-wide Stage 0 gate.
- Prepared Delhi NCR district-union boundary and India Post PIN ledger. Initial QA found seven include/exclude overlaps; remediation produced 194 unique candidates, 101 exclusions, zero overlap, deterministic hashes, and final independent QA PASS.
- New multi-city distance work uses Haversine only and labels it straight-line distance. Google center/viewport comparison is blocked by secure runtime key injection (B-007).
- Final scope-revision QA evidence: `audits/scope_revision/QA_REPORT_R2.md` and `qa_results_r2.json`.
