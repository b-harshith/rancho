# Bengaluru source mappings

Evidence review: 2026-06-30 (local files; original scrape timestamps vary). Status applies only to the inspected fixture/snapshot.

| Source | Mapping evidence | Bounded sample | Outcome |
|---|---|---|---|
| YellowSlate | Source city object in `scrape_yellowslate_fees.py`: city ID 13, name Bengaluru, slug `bengaluru`, coordinates 12.9715987/77.5945627; routes `/schools/bengaluru` and cookie keys `current_city`/`city` | First of 2,213 local location records has `/school/bengaluru/21k-school-vasanth-nagar`; source search route carried the initialized city cookie | Verified for local baseline; live reconfirmation required before rerun |
| MagicBricks Projects | Request uses numeric city ID 3327 | First record of 26,108-line fixture: `ctname=Bangalore`, Begur Koppa Road, PIN 560076, Bangalore PDP URL | Verified for local baseline; live reconfirmation required |
| 99acres Localities | Review URL `/bangalore-reviews-and-ratings-wrffid`; API configuration `20_LOCATION`; city session values exist but are secret and not evidence to publish | First page envelope includes Malleshwaram/Rajajinagar and records with `cityName=Bangalore`; fixture has 54 page envelopes | Verified for local baseline. Embedded session credentials are quarantined and must be rotated/removed |
| Practo Hospitals | Query slug `bangalore` | Local sample Motherhood Hospital, Indiranagar: `city=Bangalore`, `/bangalore/...` profile, Bengaluru description, Bangalore address region | Verified for local baseline; sample count 1, so production preflight must expand the sample |
| UDISE+ | Collection mode is PIN; `data/input/pincodes.json` is the runtime input | No authoritative PIN provenance was found in the inspected fixture | Unknown for complete geographic coverage; current OCR CAPTCHA path is prohibited |

No live request was issued for this evidence review. Request headers/cookies/tokens are intentionally omitted.
