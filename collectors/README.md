# Safe multi-city collector adapters

These adapters are deliberately fail closed. They do not perform live collection.
They resolve only verified registry mappings, validate redacted local fixture samples,
normalize fixture records with lineage, and create deterministic city-partitioned
raw/checkpoint/manifest/quarantine/normalized paths.

```bash
python -m collectors magicbricks --city hyderabad --config config/cities.yaml \
  --output-root data/cities --dry-run
python -m collectors magicbricks --city hyderabad --config config/cities.yaml \
  --output-root data/cities --fixture tests/collectors/fixtures/magicbricks_hyderabad.json \
  --sample 1 --preflight
```

All sources accept `--city`, `--config`, `--output-root`, `--resume`,
`--sample/--limit`, `--dry-run`, `--timeout`, `--retries`, `--sleep`, and
`--workers` (default 1). Network collection remains blocked until a separately
reviewed implementation is added. UDISE only emits a human-entry plan and has no
OCR/CAPTCHA code. 99acres has no embedded session and refuses to proceed without
`ACRES99_SESSION` supplied at runtime.
