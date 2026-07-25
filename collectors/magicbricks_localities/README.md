# MagicBricks localities collector

This collector is intentionally two-stage. Stage 1 walks every configured
listing page and deduplicates the locality links emitted by MagicBricks. Stage
2 opens every unique discovered link and extracts its stable locality ID,
coordinates and detail metrics. A run is not complete while any discovered
detail URL is missing.

The config is the source-mapping gate. Never synthesize a city slug or ID.
`delhi_ncr.example.json` records the five source components verified on
2026-06-30. Each component keeps its own source ID/name in normalized output.

```bash
python -m collectors.magicbricks_localities \
  --city delhi_ncr \
  --config collectors/magicbricks_localities/delhi_ncr.example.json \
  --output-root DATA/multicity \
  --resume --timeout 30 --retries 3 --sleep 3 --workers 1
```

Use `--dry-run` to inspect the resolved mapping without network access.
`--sample` limits listing pages per component and `--limit` limits details;
these are diagnostic modes and cannot establish production completeness.

Outputs are city-partitioned. Raw HTML is append-only/content-addressed,
request metadata contains hashes but no cookies or credentials, checkpoints
are atomic, parse failures/challenges are quarantined, and `manifest.json`
reports detail-stage completeness.
