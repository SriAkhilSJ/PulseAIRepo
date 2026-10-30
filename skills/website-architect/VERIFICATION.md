# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 31 |
| `cloud-and-devops-architect/` | 36 |
| `data-engineering-architect/` | 29 |
| `desktop-architect/` | 9 |
| `mobile-architect/` | 13 |
| `website-architect/` | 76 |
| **total** | **194** |

## Breadth status

| Domain | Books | Status |
|---|---|---|
| `website-architect/` | 76 | reference resolution |
| `cloud-and-devops-architect/` | 36 | at reference resolution, 7 shelves |
| `ai-ml-architect/` | 31 | at reference resolution, 8 shelves |
| `data-engineering-architect/` | 29 | at reference resolution, 7 shelves |
| `mobile-architect/` | 13 | deepened once; not yet at reference resolution |
| `desktop-architect/` | 9 | deepened once; not yet at reference resolution |

## Spec conformance

- files checked: **194**
- name == parent directory: **194/194**
- crusor-path == path from skills/: **194/194**
- unique names: **194/194**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **194/194**

## Runtime

- discovered as bundled skills: **214**
- phase = planning: **194**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| set up our aws accounts | aws-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| our cloud bill doubled | cost-optimization-architect |
| should we use snowflake or iceberg | iceberg-architect, snowflake-architect, warehouse-architect |
| grain is wrong in the fact table | sql-modelling-architect |
| we need cdc from postgres | batch-pipeline-architect, cdc-architect, db-connector, mcp, postgres-architect |
| partner sends us csv files on sftp | file-ingestion-architect |
| kafka topic partition count | kafka-architect, streaming-architect |
| flink watermarks never fire | batch-pipeline-architect, flink-architect, streaming-architect |
| schema registry compatibility mode | event-schema-architect, graphql-architect, typescript-architect |
| dbt incremental model has duplicates | analytics-engineering-architect, data-quality-architect, dbt-architect |
| spark job is slow because of skew | batch-pipeline-architect, spark-architect |
| duckdb instead of a warehouse | duckdb-architect |
| impact analysis before renaming a column | lineage-architect |
| pii masking in the warehouse | governance-architect |
| airflow backfill stuck | airflow-architect, batch-pipeline-architect, orchestration-architect |
| dagster assets design | dagster-architect, orchestration-architect |
| one metric definition for revenue | analytics-engineering-architect, semantic-layer-architect |
| sync scores into salesforce | reverse-etl-architect |
| our dashboards show stale data | data-observability-architect, mobile-offline-sync-architect, observability-architect, sre-observability-architect |
| expose analytics to partners via api | data-api-architect, data-engineering-architect |
| which model should we pick for support | model-selection-architect |
| prompt injection through support tickets | ai-ml-architect, prompting-architect, red-teaming-architect |
| build an ios app with swiftui | ios-architect, ios-swiftui-architect, mobile-architect |
| app works offline in the field | mobile-architect, mobile-offline-sync-architect, pwa-architect |
| electron app needs a secure bridge | desktop-architect, desktop-ipc-architect, electron-architect |
| design a rest api | rest-architect, rest-graphql-debug |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures.
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed.
- `pytest src/tests/test_skill_library.py` → 13 passed.

## Known gaps

- All skills are `crusor-origin: original`: GitHub access is unavailable here, so no body is adapted from an upstream repository.
- mobile (13) and desktop (9) are still below reference resolution; the breadth pass continues there.
- The MCP hierarchy mirroring this tree is not built yet.
