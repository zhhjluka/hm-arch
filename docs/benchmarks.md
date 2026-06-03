# PRD scale and performance benchmarks (HM-31)

Reproducible offline benchmarks validate the HM-Arch PRD performance contract for
single-process, local-fallback operation (SQLite + deterministic token-overlap
vectors). They do **not** measure distributed load, provider latency, or API cost.

Source contract: original HM-Arch developer PRD (referenced in `docs/spec.md`) and
`docs/tasks.md` HM-31 acceptance criteria.

## Two PRD performance tables

The developer PRD defines **two** tables. Benchmarks report both; primary
**assertions** use the test-benchmark table.

### Test benchmark (acceptance)

| Metric | PRD limit | Conditions |
|--------|-----------|------------|
| `add()` p95 | ≤ **50 ms** | Steady state after warmup |
| `search(top_k=10)` p95 | ≤ **100 ms** | 10,000 active L2 rows |
| `consolidate()` | ≤ **60 s** | 10,000 L2 rows; default `replay_sample_ratio=0.20` |
| SQLite storage | **< 500 MB** | 10,000 L2 + 5,000 L3 active triples |

### Week 9 optimization (stretch)

| Metric | PRD limit | Notes |
|--------|-----------|--------|
| `add()` | < **30 ms** | Aspirational post-optimization |
| `search()` | < **50 ms** | Same 10k L2 scale |
| `consolidate()` | < **5 s** | Same 10k L2 scale |

Each run records `contract_compliance` in the JSON report with `observed`, `limit`,
`comparison`, and `pass` for **both** tables. Week 9 rows are stretch goals stored in
`stretch_assertions`; only `assertions` (test-benchmark + scenario gates) determine
acceptance for MEM-31 and for `scripts/run_prd_benchmarks.py` exit code.

Constants: `benchmarks/prd_targets.py` (`PrdTestBenchmarkTargets`, `PrdWeek9OptimizationTargets`).

## Scenario contracts

| Scenario | PRD expectation | Benchmark |
|----------|-----------------|-----------|
| 7-day semantic extraction | 50 **conversation** events/day, 1 `consolidate()`/day, day-7 L3 accuracy **> 80%** | `seven_day_semantic` in harness |
| L4 archive threshold (mixed age) | Episodes below `l2_archive_threshold` archive to L4 | `l4_archive_mixed_age` (74% at 90d / 26% at 30d) |
| L4 uniform 30-day retention | L2 ≈ 0.26 at 30 days (theoretical) | `l4_uniform_30d` — reports actual archive count |
| 30-day retention curves | L2 ≈ 0.26, L3 ≈ 0.63 at 30 days | `tests/test_simulation_30_day.py` (fast CI) |

7-day accuracy: expected triples are derived from episode text (unique `agent{day}_{i}`
subjects so facts do not supersede). Accuracy = matched / expected active L3 triples.
The contract uses **>** 80% (exactly 80% does not pass).

### PRD L4 archive inconsistency (documented honestly)

The developer PRD cites two related but distinct numbers:

- **30-day L2 retention** ≈ **0.26** (forgetting curve reference)
- **Archive target** sometimes written as `L2 × (1 − 0.26)` ≈ **7400** archived from 10k L2

Implementation archives when `current_retention < l2_archive_threshold` (default **0.15**).
Uniform 30-day L2 rows retain **above** 0.15, so they **stay active** — the formula
does not match threshold-based archiving.

The **mixed-age** benchmark (74% back-dated 90 days, 26% at 30 days) produces ~7400
archives **by construction** (the old fraction), not by validating the retention formula.
The **uniform 30-day** benchmark reports the real outcome: ~0 archives with ~10k active L2.
Long-run retention behavior remains covered by `tests/test_simulation_30_day.py`.

## Commands

### Default CI / daily development (fast)

```bash
uv run pytest
```

Benchmarks are excluded via `addopts = -m "not benchmark"`.

### PRD benchmark suite (slow, ~2–3 minutes)

```bash
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run python scripts/run_prd_benchmarks.py
uv run python scripts/run_prd_benchmarks.py --output /tmp/prd_benchmark.json
```

### MEM-31 verification bundle

```bash
uv run pytest tests/test_simulation_30_day.py
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run pytest
```

## Methodology

1. **Environment** — Python version, `platform.platform()`, processor, UTC timestamp.
2. **Isolation** — Fresh temp DB + L4 root per scenario; `auto_consolidate=False`.
3. **Latency** — `time.perf_counter()`; p95 via nearest-rank on sorted samples.
4. **Add** — 50 warmup + 200 measured adds.
5. **Search @ 10k** — Seed 10,000 L2, then 100× `search(..., top_k=10)`.
6. **Consolidate @ 10k** — One cycle, default replay ratio.
7. **Storage** — `get_stats().storage_size_mb` after 10k L2 + 5k L3 upserts.
8. **7-day** — 50× `EventType.CONVERSATION` per day × 7, nightly `consolidate()`.
9. **L4 mixed age** — Separate DB; 74% at 90d / 26% at 30d; assert archive count ≈ old fraction.
10. **L4 uniform 30d** — Separate DB; all rows at 30d; report retention vs threshold and actual archives.

Boundary operators match the PRD tables: test-benchmark latency uses `<=`, storage uses `<`,
Week 9 uses `<`, and 7-day accuracy uses `>`.

## Example observed results

Cloud Agent VM (2026-06-03, Linux, Python 3.12, local fallback):

| Metric | Observed | Test benchmark | Week 9 | Test pass | Week 9 pass |
|--------|----------|----------------|--------|-----------|-------------|
| `add()` p95 | ~3.8 ms | ≤ 50 ms | < 30 ms | yes | yes |
| `search()` p95 @ 10k | ~73 ms | ≤ 100 ms | < 50 ms | yes | varies* |
| `consolidate()` @ 10k | ~0.9 s | ≤ 60 s | < 5 s | yes | yes |
| Storage 10k L2 + 5k L3 | ~8.5 MB | < 500 MB | — | yes | — |
| 7-day semantic accuracy | 100% | > 80% | — | yes | — |
| L4 mixed-age archived @ 10k | ~7400 | old fraction ±5% | — | yes | — |
| L4 uniform 30d archived @ 10k | 0 | formula would be ~7400* | — | yes | — |

\*PRD formula `L2 × (1 − 0.26)` assumes retention maps to archive count; uniform 30-day
rows retain above `l2_archive_threshold` (0.15) and stay active. See **PRD L4 archive inconsistency** above.

\*Week 9 search passes on some hosts (e.g. macOS arm64 ~59 ms) and may not on others (~73 ms). Re-run locally; stretch goals are in `stretch_assertions` and do not affect acceptance exit code.

Re-run `scripts/run_prd_benchmarks.py` for authoritative numbers on your hardware.
