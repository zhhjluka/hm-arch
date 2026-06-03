# PRD scale and performance benchmarks (HM-31)

Reproducible offline benchmarks validate the HM-Arch PRD performance contract for
single-process, local-fallback operation (SQLite + deterministic token-overlap
vectors). They do **not** measure distributed load, provider latency, or API cost.

Source contract: original HM-Arch developer PRD (referenced in `docs/spec.md`) and
`docs/tasks.md` HM-31 acceptance criteria.

## PRD targets (offline, local fallback)

| Metric | Target | Conditions |
|--------|--------|------------|
| `add()` p95 latency | ≤ 50 ms | After warmup; steady-state single writes |
| `search()` p95 latency | ≤ 200 ms | 10,000 active L2 episodic rows |
| `consolidate()` wall time | ≤ 120 s | 10,000 L2 rows; `replay_sample_ratio=0.20` (default) |
| L2 corpus | 10,000 episodes | Measured storage via `get_stats().storage_size_mb` |
| L3 corpus | 5,000 active triples | Upserted after L2 seed (additive storage) |
| L4 archive | ≥ 1 archived row + on-disk gzip | Stale L2 back-dated 90 days |
| 7-day semantic loop | L3 preference + L4 growth + review queue | Nightly `consolidate()` × 7 |

Long-run **30-day** retention (L2 ≈ 0.26, L3 ≈ 0.63), preference supersession, and
review-queue behavior are validated in the fast simulation suite:

```bash
uv run pytest tests/test_simulation_30_day.py
```

## Commands

### Default CI / daily development (fast)

Benchmarks are **excluded** via the `benchmark` pytest marker:

```bash
uv run pytest
```

### PRD benchmark suite (slow, ~1–2 minutes)

```bash
uv run pytest tests/prd_benchmarks -m benchmark -v
```

Or the standalone script (prints JSON + assertion summary):

```bash
uv run python scripts/run_prd_benchmarks.py
uv run python scripts/run_prd_benchmarks.py --output /tmp/prd_benchmark.json
```

### Issue HM-31 / MEM-31 verification bundle

```bash
uv run pytest tests/test_simulation_30_day.py
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run pytest
```

## Methodology

1. **Environment** — Recorded in each report: Python version, `platform.platform()`,
   processor, UTC timestamp (`benchmarks.harness.collect_environment()`).
2. **Isolation** — Each scenario uses a fresh temp directory with its own SQLite DB
   and L4 archive root (`auto_consolidate=False` to avoid background ticks).
3. **Latency** — `time.perf_counter()`; p95 computed with nearest-rank on sorted samples.
4. **Add latency** — 50 warmup adds, then 200 measured adds on a modest corpus.
5. **Search @ 10k** — Seed 10,000 L2 episodes, then 100 search calls (`top_k=10`).
6. **Consolidate @ 10k** — One cycle with default `replay_sample_ratio`; report
   `ConsolidationReport` fields and wall time.
7. **Storage** — `HMArch.get_stats()` after 10k L2 + 5k L3 upserts.
8. **7-day scenario** — Seven synthetic days: preference + code episodes, back-dated
   timestamps, nightly `consolidate()` (matches `tests/test_consolidation.py`).

## Recording results

After a run, paste the JSON `environment`, `results`, and `assertions` sections into
release notes or the Linear issue. Note any hardware differences (CPU, disk, Python
version). If a target is missed, document the measured value and whether it is an
environment limitation or a product gap — do not change product code solely to pass
benchmarks unless a correctness bug is found.

## Example observed results

Recorded on the Cloud Agent VM (2026-06-03, `linux`, Python 3.12, local fallback):

| Metric | Observed | PRD target | Pass |
|--------|----------|------------|------|
| `add()` p95 | ~3.8 ms | ≤ 50 ms | yes |
| `search()` p95 @ 10k L2 | ~73 ms | ≤ 200 ms | yes |
| `consolidate()` @ 10k L2 | ~0.9 s | ≤ 120 s | yes |
| SQLite after 10k L2 + 5k L3 | ~8.5 MB | (documented) | — |

Re-run `scripts/run_prd_benchmarks.py` on your machine for authoritative numbers.
