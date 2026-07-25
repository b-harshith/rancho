# Rancho deletion manifest — 2026-07-19

Status: **completed**

Final result:

- `Desktop/BangaloreRancho` now contains only the canonical workspace.
- Rancho storage was reduced from roughly 35-36 GiB across the Desktop to about 529 MiB.
- Available disk space increased from about 1.3 GiB to about 42 GiB after the
  project cleanup and the separately approved AI-tool cleanup.
- All six final-data checksums pass.
- The Vercel project link, configuration, deployed public data and runtime data remain.
- Post-cleanup tests: 86 run, 85 passed and 1 explicitly skipped because its optional
  21 MiB raw benchmark fixture was intentionally removed.
- No virtual environments, Node modules, Python bytecode caches, raw scrape databases,
  or Vercel build caches remain in the canonical folder.

This manifest records storage removed after the canonical keep-set passed final-data
checksums, Python parsing, active-path checks, and 86 unit tests.

## Consolidated before deletion

- Final multi-city source data moved to `final_data/multicity_source/`.
- Final Bengaluru TAM data retained in `DATA/final/` and `maps/final/`.
- Scraper source/config/dependency manifests retained under `external_scrapers/`.
- Processing source retained under `archived_pipelines/`.
- Vercel source/runtime/static data and project binding retained under `src/`.
- Final school report retained under `final_data/reports/`.
- Rancho Noida legacy assignment retained under `legacy_projects/noida_assignment/`.
- Live `.env` credentials and historical browser sessions were not copied.

## External raw/intermediate workspaces selected for permanent removal

- `Desktop/school extraction` — about 7.6 GiB.
- `Desktop/final new data` remainder — final data already moved; about 309 MiB remains.
- `Desktop/foursquare categories` — about 343 MiB.
- `Desktop/School Data` — about 160 MiB.
- `Desktop/CatchmentIQ` — about 1.4 GiB.
- `Desktop/Rancho Labs` — about 895 MiB.
- `Desktop/Harshith files/final try` — about 3.3 GiB.
- `Desktop/Harshith files/data of 15 cities magic bricks` — about 1.9 GiB.
- Desktop `magicbricks_raw.jsonl` — about 255 MiB.
- Duplicate/older final school and workbook files under `Harshith files`.

## Superseded material inside `Desktop/BangaloreRancho`

- Root `DATA/` — about 7.5 GiB, including generated OSRM and duplicate Overture data.
- `web_platform_vercel_exact_latest_copy` — about 3.8 GiB.
- `city_rerun_bundle` data workspace — about 952 MiB; code retained separately.
- Old `web_platform` and `web_platform_vercel_previous_deployment` — about 188 MiB.
- Root maps/scripts and raw office file after their required code/final output was retained.

## Generated material inside the canonical workspace

- Raw/intermediate `DATA` subfolders other than `DATA/final`.
- Vercel build cache/output/Python runtime, local virtual environments, Node modules,
  Python bytecode, temporary outputs, old raw maps, and raw 99acres input.

Moving these items to Trash would not recover storage, so the selected targets are
permanently deleted. The removed scrape data is reproducible from retained source code
subject to fresh authorized credentials/sessions and current source availability.

## AI-tool cache and Rancho-history cleanup

The user separately approved aggressive removal of Rancho-specific AI histories and
regenerable AI-tool caches while preserving unrelated project histories and tool state.

Permanently deleted without using Trash:

- 315 Rancho-linked Antigravity artifacts across 111 matched conversation IDs:
  conversations, generated brain artifacts, implicit state and browser recordings —
  5,912.4 MiB.
- 134 Rancho-linked historical Codex session files — 276.3 MiB. The two files tied to
  the active cleanup task were explicitly excluded.
- Four Rancho/CatchmentIQ Cursor project-history folders — 1.8 MiB.
- 61 regenerable AI-tool cache targets — 5,008.6 MiB. These included downloaded Codex
  runtimes, Puppeteer browser binaries, model/package caches, Antigravity updater and
  application caches, browser cache stores, Codex browser caches, and AI-tool logs.

AI-tool deletion total: 514 validated targets and 10.937 GiB, with zero deletion
failures. Post-cleanup scanning found no remaining matched Antigravity artifact and no
remaining deletable Rancho Codex history outside the active task. The running Codex app
regenerated about 0.2 MiB of cache immediately; this is expected.

Preserved and verified after deletion:

- Antigravity and Antigravity IDE settings, MCP configuration and extensions.
- Antigravity browser cookies and login databases.
- Codex plugins, skills and the active cleanup task.
- ChatGPT conversation data.
- Non-Rancho Antigravity, Codex and Cursor histories.
