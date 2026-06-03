# PRD scale and performance benchmarks (HM-31)

Reproducible offline benchmarks validate the HM-Arch PRD performance contract for
single-process, local-fallback operation (SQLite + deterministic token-overlap
vectors). They do **not** measure distributed load, provider latency, or API cost.

Source contract: original HM-Arch developer PRD (referenced in `docs/spec.md`) and
`docs/tasks.md` HM-31 acceptance criteria.

## Two PRD performance tables

The developer PRD defines **two** tables. Benchmarks report both in
`contract_compliance`; **only the test-benchmark table gates acceptance**
(`report.assertions` and `scripts/run_prd_benchmarks.py` exit code).

### Test benchmark (acceptance)

| Metric | PRD limit | Comparison |
|--------|-----------|------------|
| `add()` p95 | **50 ms** | observed **<** limit |
| `search(top_k=10)` p95 @ 10k L2 | **100 ms** | observed **<** limit |
| `consolidate()` @ 10k L2 | **60 s** | observed **<** limit |
| SQLite storage (10k L2 + 5k L3) | **500 MB** | observed **<** limit |
| 7-day L3 semantic accuracy | **80%** | observed **>** limit |

Boundary values (e.g. exactly 100 ms search p95) **fail** acceptance.

### Week 9 optimization (stretch, report-only)

| Metric | PRD limit | Notes |
|--------|-----------|--------|
| `add()` p95 | **30 ms** | In `contract_compliance` only |
| `search()` p95 | **50 ms** | Does not fail the benchmark runner |
| `consolidate()` | **5 s** | Informational on slower hosts |

Each run records `contract_compliance` with `observed`, `limit`, `comparison`, and
`pass` for both tables. Week 9 misses are printed to stderr but do not affect exit code.

Constants: `benchmarks/prd_targets.py`.

## Scenario contracts

| Scenario | What it validates |
|----------|-------------------|
| 7-day semantic | 50 `CONVERSATION` events/day × 7, nightly `consolidate()`, accuracy **> 80%** |
| L4 uniform 30d @ 10k | Real outcome when all L2 rows are uniformly 30 days old |
| L4 mixed-age @ 10k | Archive-threshold **capacity** (74% @ 90d / 26% @ 30d by construction) |
| 30-day agent L4 ratio | Empirical archive fraction after simulated agent loop (±20% vs formula) |
| 30-day retention curves | L2 ≈ 0.26, L3 ≈ 0.63 | `tests/test_simulation_30_day.py` (fast CI) |

### PRD L4 archive formula deviation (documented)

The PRD sometimes states archived L4 ≈ `L2 × (1 − 0.26)` after long-run decay.
That is **internally inconsistent** with uniform 30-day aging:

- Modeled **30-day** L2 retention ≈ **0.26**
- `l2_archive_threshold` = **0.15**
- Uniform 30-day-old rows therefore **do not archive** (retention > threshold)

Reported in `l4_prd_retention_archive_deviation` and `l4_archive_10k_uniform_30d`
(typically **0** archives; formula predicts ~7400).

The **mixed-age** inject preselects 74% at 90 days — a threshold/capacity test, not
uniform 30-day validation.

The **30-day agent simulation** (`test_prd_thirty_day_archive.py`) archives stale
code episodes (45+ day back-dates) over nightly consolidation; it measures an
empirical ratio with ±20% tolerance — not a proof that uniform 30-day rows satisfy
the formula.

## Commands

### Default CI (fast)

```bash
uv run pytest
```

Benchmarks excluded via `addopts = -m "not benchmark"`.

### PRD benchmark suite (~2–3 minutes)

```bash
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run python scripts/run_prd_benchmarks.py
```

Week 9 misses print as **informational** stderr; exit code 1 only on acceptance failures.

### 30-day L4 archive ratio only (slow)

```bash
uv run pytest tests/prd_benchmarks/test_prd_thirty_day_archive.py -m benchmark -v
```

### MEM-31 verification bundle

```bash
uv run pytest tests/test_simulation_30_day.py
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run pytest
```

## Example observed results

Linux VM (2026-06-03, Python 3.12, local fallback):

| Metric | Observed | Test benchmark | Week 9 (report) |
|--------|----------|----------------|-----------------|
| add p95 | ~3.8 ms | < 50 ms ✓ | < 30 ms ✓ |
| search p95 @ 10k | ~73 ms | < 100 ms ✓ | < 50 ms (varies) |
| consolidate @ 10k | ~0.9 s | < 60 s ✓ | < 5 s ✓ |
| storage 10k+5k | ~8.5 MB | < 500 MB ✓ | — |
| 7-day accuracy | 100% | > 80% ✓ | — |
| L4 uniform 30d | 0 archived | formula predicts ~7400 (not met) | — |
| L4 mixed-age | 7400 archived | threshold capacity test | — |

Re-run `scripts/run_prd_benchmarks.py` on your hardware for authoritative numbers.
