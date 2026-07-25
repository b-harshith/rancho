# Source mapping evidence

These files are evidence records, not a list of plausible slugs. A mapping is `verified` only when the source's own selector/rendered state/network request and a bounded sample agree. Secrets and CAPTCHA values must be redacted. Unknown values stay unknown.

Required evidence for each source: UTC discovery timestamp; exact page URL; redacted request shape; returned city label/ID; sample record names and locality/address/PIN evidence; sample/result count; validation numerator/denominator; outcome (`verified`, `failed`, or `unknown`); and reviewer. For Delhi NCR, record every source component separately and explain canonical roll-up/deduplication.

Preflight acceptance: sample only one page; at least 90% city/region matches; no repetition of another city's known fixture. A CAPTCHA/challenge, authorization failure, ambiguous city label, or missing selector evidence is a blocker—not permission to guess.
