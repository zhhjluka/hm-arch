# HM-Arch API reference

_Generated from `hm_arch` v2.0.2. Regenerate with `python scripts/generate_api_docs.py`._

Stable integrations should import from the top-level package:

```python
from hm_arch import HMArch, MemoryConfig, EventType
```

Advanced lifecycle helpers live in ``hm_arch.forgetting``:

```python
from hm_arch.forgetting import ManualTimeProvider, ForgettingController
from hm_arch.forgetting import compute_initial_strength, strength_bounds
```

Layer implementations (`hm_arch.layers`) are available for advanced
use but are not required for the primary agent workflow.

---

## Package exports (`hm_arch`)

| Name | Kind |
|------|------|
| `__version__` | str |
| `HMArch` | class |
| `AgentContext` | export |
| `MemoryConfig` | dataclass |
| `EventType` | enum |
| `MemoryProvenance` | export |
| `MemoryReceipt` | dataclass |
| `MemoryItem` | dataclass |
| `SearchResult` | dataclass |
| `ConsolidationReport` | dataclass |
| `RetentionCurve` | dataclass |
| `MemoryStats` | dataclass |
| `ForgetResult` | dataclass |

---

## `HMArch`

### `HMArch.__init__`

Create an :class:`HMArch` memory store.

Parameters
----------
db_path:
    SQLite database path.  Ignored when *config* is supplied.
config:
    Optional runtime configuration.
time_provider:
    Injectable clock for deterministic lifecycle tests.  Defaults to
    :class:`~hm_arch.forgetting.time.SystemTimeProvider`.

```python
HMArch.__init__(self, db_path: 'str' = './.agent_memory.db', config: 'Optional[MemoryConfig]' = None, *, time_provider: 'Optional[TimeProvider]' = None) -> 'None'
```

### `HMArch.add`

Store *content* in L0, L1, and the episodic buffer (L2).

``add()`` always succeeds without an external LLM key when capacity
limits allow.  L3 semantic extraction is **not** triggered here; it
happens during ``consolidate()``.

Parameters
----------
content:
    Text to remember.
event_type:
    Classification for the event; defaults to
    :attr:`~hm_arch.types.EventType.CONVERSATION`.
metadata:
    Optional key/value pairs attached to the memory record.
importance:
    Importance score in ``[0, 1]``.  When omitted the L2 layer
    default (``0.5``) is applied.
agent:
    Optional agent name recorded as provenance.
project:
    Optional project path or identifier recorded as provenance.
session:
    Optional host-agent session identifier recorded as provenance.

Returns
-------
MemoryReceipt
    Confirmation including the ``memory_id`` assigned by L2, which
    is the durable database-backed identifier for the event.

```python
HMArch.add(self, content: 'str', event_type: 'EventType' = <EventType.CONVERSATION: 'conversation'>, metadata: 'Optional[dict]' = None, importance: 'Optional[float]' = None, *, agent: 'str | None' = None, project: 'str | None' = None, session: 'str | None' = None) -> 'MemoryReceipt'
```

### `HMArch.search`

Return the top-*k* memories most relevant to *query*.

Queries L0 sensory register, L1 working memory, L2 episodic buffer,
L3 semantic memory, and L4 archived episodic memories.  Candidates from
all layers are merged,
``memory_id``, scored as::

    score = retention × relevance × layer_priority

and sorted descending so the highest-scoring result is first.

CJK text is tokenised character-by-character so queries like
``"用户喜欢什么语言"`` match content like ``"用户偏好 Python"`` via
shared character tokens.

Parameters
----------
query:
    Free-text search string.
top_k:
    Maximum number of :class:`~hm_arch.types.MemoryItem` results to
    return.  Defaults to ``10`` (PRD).
min_retention:
    Exclude hits whose retention is strictly below this value.
    Defaults to ``0.1`` (PRD).
layer_filter:
    When provided, only search these layer indices (e.g. ``[1, 2, 3]``).
    When ``None``, all supported layers ``(0, 1, 2, 3, 4)`` are queried.

L6 policies ``retrieval_top_k_multiplier`` and ``prefer_hot_memories``
adjust the effective *top_k* and ranking scores when configured.

Returns
-------
SearchResult
    Container with ranked :class:`~hm_arch.types.MemoryItem` hits
    plus diagnostic metadata (total candidates scanned, timing,
    per-layer breakdown).

```python
HMArch.search(self, query: 'str', top_k: 'int' = 10, *, min_retention: 'float' = 0.1, layer_filter: 'list[int] | None' = None) -> 'SearchResult'
```

### `HMArch.forget`

Forget one memory or run a context-aware global forgetting scan.

When *memory_id* is provided, only that memory is considered.  When
``memory_id`` is ``None``, eligible rows are evaluated with the PRD
context-aware forgetting score (retention, relevance, redundancy,
contradiction, privacy).  Only candidates whose composite score meets
``config.forgetting_score_threshold`` are removed.

With ``memory_id is None`` and ``force=False``, only ``deletable`` rows
are scanned.  With ``force=True``, active rows below the layer delete
threshold are included as well.  Automated lifecycle physical cleanup
still waits for ``deletion_safety_period_hours``; this method performs
immediate removal for score-qualified candidates.

L2 memories below the archive threshold are moved to L4 when possible;
otherwise they are marked ``deleted``.  Archived L4 rows purge the gzip
artifact.  L3 rows are marked ``deleted`` and removed from the vector
index.

Parameters
----------
memory_id:
    Target memory identifier, or ``None`` for a global scan.
force:
    When ``True``, include active low-retention rows in the global scan.

Returns
-------
ForgetResult
    Structured counts and per-memory actions.

```python
HMArch.forget(self, memory_id: 'str | None' = None, *, force: 'bool' = False) -> 'ForgetResult'
```

### `HMArch.consolidate`

Run a consolidation cycle: decay, replay, semantic extraction, reviews.

Applies layer-specific retention decay, replays a sample of L2 episodes
through the offline semantic extractor, upserts triples into L3, and
schedules reviews for important low-retention memories.  No external
LLM key is required.

```python
HMArch.consolidate(self) -> 'ConsolidationReport'
```

### `HMArch.run_lifecycle`

Run one automatic lifecycle tick.

Applies due auto-consolidation (when enabled) and conservative
physical cleanup for score-qualified ``deletable`` rows past
``deletion_safety_period_hours``.

```python
HMArch.run_lifecycle(self) -> 'None'
```

### `HMArch.get_retention_curve`

Return predicted retention samples for L2 or L3 decay curves.

Supports the PRD positional form ``get_retention_curve(memory_id,
days_ahead=90)`` as well as the layer-based form
``get_retention_curve(layer=2)``.

Parameters
----------
layer_or_memory_id:
    When an ``int`` in ``(2, 3)``, selects the layer decay curve.
    When a ``str``, treated as *memory_id* (PRD positional call).
days_ahead:
    Maximum day offset to sample when building the default day list.
    Ignored when *days* is provided.
layer:
    Keyword-only layer index (overrides *layer_or_memory_id* when set).
memory_id:
    Keyword-only memory identifier (overrides *layer_or_memory_id*).
days:
    Optional sorted day offsets to sample; defaults to PRD checkpoints
    up to *days_ahead*.

```python
HMArch.get_retention_curve(self, layer_or_memory_id: 'Union[int, str]' = 2, days_ahead: 'int' = 90, *, layer: 'int | None' = None, memory_id: 'str | None' = None, days: 'list[int] | None' = None) -> 'RetentionCurve'
```

### `HMArch.get_stats`

Return aggregated statistics about the memory store.

Counts include in-session L0/L1 items, persisted L2/L3 active rows,
archived L4 index rows, L5 skills, and L6 persisted ``meta_memory`` rows.
Retention histogram buckets are computed from ``memory_index`` for
active persisted memories.  :attr:`~MemoryStats.archive_storage_mb`
reports on-disk L4 gzip usage.

```python
HMArch.get_stats(self) -> 'MemoryStats'
```

### `HMArch.store_skill`

Persist or update a procedural skill in L5.

```python
HMArch.store_skill(self, name: 'str', *, description: 'str | None' = None, code: 'str | None' = None) -> 'SkillRecord'
```

### `HMArch.match_skill`

Return the best-matching L5 skill for *query*, or ``None``.

```python
HMArch.match_skill(self, query: 'str', *, record_usage: 'bool' = True) -> 'SkillRecord | None'
```

### `HMArch.list_skills`

Return all L5 skills sorted by name.

```python
HMArch.list_skills(self) -> 'list[SkillRecord]'
```

### `HMArch.record_skill_result`

Record the outcome of applying an L5 skill.

```python
HMArch.record_skill_result(self, skill_id_or_name: 'str', success: 'bool', *, duration_ms: 'float | None' = None) -> 'SkillRecord'
```

### `HMArch.get_skill`

Return an L5 skill by id or name without matching.

```python
HMArch.get_skill(self, skill_id_or_name: 'str') -> 'SkillRecord | None'
```

### `HMArch.set_policy`

Persist an L6 policy that tunes retrieval or consolidation.

```python
HMArch.set_policy(self, name: 'str', value: 'str') -> 'None'
```

### `HMArch.get_policy`

Return an L6 policy value (built-in default when unset).

```python
HMArch.get_policy(self, name: 'str') -> 'str'
```

### `HMArch.get_hot_memories`

Return frequently accessed memories tracked by L6.

```python
HMArch.get_hot_memories(self, limit: 'int' = 10, *, layer: 'int | None' = None) -> 'list[HotMemoryRecord]'
```

### `HMArch.strategy_plan`

Return current L6 policies and deterministic recommendations.

```python
HMArch.strategy_plan(self) -> 'StrategyPlan'
```

### `HMArch.agent_context`

Return a stable :class:`~hm_arch.context.AgentContext` for this store.

```python
HMArch.agent_context(self) -> 'AgentContext'
```

### `HMArch.context`

Save and restore L1 working-memory session state.

Yields an :class:`~hm_arch.context.AgentContext` so callers can use the
PRD pattern ``with memory.context() as ctx: ctx.load_session(); ...;
ctx.save_session()``.  On exit, L1 is rolled back to the pre-block
snapshot (even when an exception is raised).  L2/L3 persisted data is
unaffected.

Existing integrations may keep using the outer ``memory`` variable for
``add()`` / ``search()`` inside the block.

Examples
--------
::

    memory.add("baseline context")
    with memory.context() as ctx:
        ctx.load_session()
        memory.add("temporary task note")
        ctx.save_session()
    # L1 is back to the pre-block snapshot; L2 still has both adds.

```python
HMArch.context(self) -> 'Iterator[AgentContext]'
```

### `HMArch.close`

Commit and close the underlying SQLite connection.

```python
HMArch.close(self) -> 'None'
```

### `HMArch.__enter__`

_No docstring._

```python
HMArch.__enter__(self) -> "'HMArch'"
```

### `HMArch.__exit__`

_No docstring._

```python
HMArch.__exit__(self, exc_type, exc_val, exc_tb) -> 'None'
```

---

## `MemoryConfig`

Runtime configuration for an :class:`HMArch` instance.

Time constants are expressed in hours, matching the PRD formulas.

| Field | Type | Description |
|-------|------|-------------|
| `db_path` | `'str'` | (default: `'./.agent_memory.db'`)|
| `archive_root` | `'Optional[str]'` ||
| `sqlite_busy_timeout_ms` | `'int'` | (default: `30000`)|
| `sqlite_lock_retries` | `'int'` | (default: `5`)|
| `sqlite_lock_retry_base_delay_s` | `'float'` | (default: `0.05`)|
| `l2_fast_tau` | `'float'` | (default: `24.0`)|
| `l2_slow_tau` | `'float'` | (default: `720.0`)|
| `l2_fast_weight` | `'float'` | (default: `0.3`)|
| `l3_tau` | `'float'` | (default: `168.0`)|
| `l3_beta` | `'float'` | (default: `0.3`)|
| `initial_ef` | `'float'` | (default: `2.5`)|
| `min_ef` | `'float'` | (default: `1.3`)|
| `review_trigger_retention` | `'float'` | (default: `0.5`)|
| `l2_archive_threshold` | `'float'` | (default: `0.15`)|
| `l2_delete_threshold` | `'float'` | (default: `0.05`)|
| `l3_archive_threshold` | `'float'` | (default: `0.3`)|
| `l3_delete_threshold` | `'float'` | (default: `0.1`)|
| `redundancy_threshold` | `'float'` | (default: `0.85`)|
| `auto_consolidate` | `'bool'` | (default: `True`)|
| `consolidate_interval_hours` | `'int'` | (default: `24`)|
| `deletion_safety_period_hours` | `'int'` | (default: `168`)|
| `forgetting_score_threshold` | `'float'` | (default: `0.35`)|
| `replay_sample_ratio` | `'float'` | (default: `0.2`)|
| `strength_min` | `'float'` | (default: `0.2`)|
| `strength_max` | `'float'` | (default: `6.75`)|
| `retrieval_reinforcement_increment` | `'float'` | (default: `0.3`)|
| `retrieval_relevance_threshold` | `'float'` | (default: `0.25`)|
| `l0_capacity` | `'int'` | (default: `7`)|
| `max_memories_l2` | `'int'` | (default: `100000`)|
| `max_memories_l3` | `'int'` | (default: `50000`)|
| `max_skills_l5` | `'int'` | (default: `10000`)|
| `enable_llm_providers` | `'bool'` | (default: `False`)|
| `provider_fallback_to_local` | `'bool'` | (default: `True`)|
| `llm_provider` | `'str'` | (default: `'local'`)|
| `llm_model` | `'Optional[str]'` ||
| `llm_api_key` | `'Optional[str]'` ||
| `llm_base_url` | `'Optional[str]'` ||
| `embedding_provider` | `'str'` | (default: `'local'`)|
| `embedding_model` | `'Optional[str]'` ||
| `embedding_dim` | `'int'` | (default: `384`)|
| `vector_backend` | `'str'` | (default: `'local'`)|
| `chroma_persist_directory` | `'Optional[str]'` ||
| `chroma_collection_prefix` | `'str'` | (default: `'hm_arch'`)|
| `enable_sensitive_data_filter` | `'bool'` | (default: `True`)|
| `sensitive_data_patterns` | `'list[str]'` | (factory)|
| `max_stored_content_chars` | `'int'` | (default: `16384`)|
| `sensitive_data_redaction_token` | `'str'` | (default: `'[REDACTED]'`)|
| `layer_priorities` | `'dict[str, float]'` | (factory)|

### Presets

`MemoryConfig.preset(name)` — `name` is one of:

- `code_agent`
- `chat_agent`
- `research_agent`

---

## Optional providers and vector backends (HM-30)

HM-Arch is **offline-first**. Local token-overlap search and pattern-based
semantic extraction are the defaults. Remote LLM, embedding, and ChromaDB
backends are opt-in and never required for tests or demos.

### Opt-in switch

| Setting | Default | Effect |
|---------|---------|--------|
| `enable_llm_providers` | `False` | When `False`, all provider fields are ignored; local heuristics and `vector_backend='local'` are used. |
| `provider_fallback_to_local` | `True` | When `True`, missing API keys, missing optional packages, and **runtime** provider HTTP/parsing failures fall back to local implementations. When `False`, those conditions raise actionable errors. |

### LLM providers (`llm_provider`)

| Value | Chat API | Default model when `llm_model` is unset |
|-------|----------|----------------------------------------|
| `local` | None (heuristic importance + pattern triples) | — |
| `openai` | OpenAI-compatible `/chat/completions` | `gpt-4o-mini` |
| `deepseek` | DeepSeek `/chat/completions` | `deepseek-chat` |

Set `llm_api_key` or `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` (also `HM_ARCH_*` variants).
Optional `llm_base_url` overrides the provider host.

Provider-backed importance scoring runs in `HMArch.add()` when `enable_llm_providers=True`. Provider-backed semantic extraction runs in `HMArch.consolidate()` via `ProviderSemanticExtractor`.

### Embedding providers (`embedding_provider`)

| Value | Supported | Notes |
|-------|-----------|-------|
| `local` | Yes | Deterministic hash embeddings (default). |
| `openai` | Yes | `/embeddings`; default model `text-embedding-3-small` when unset. |
| `deepseek` | **No** | DeepSeek's public API does not document embeddings. With fallback enabled, local embeddings are used; otherwise configuration raises. |

`embedding_dim` is enforced for OpenAI embeddings: v3 models send a `dimensions` request field; every returned vector must match `embedding_dim` or the provider falls back locally / raises `ProviderRuntimeError` per `provider_fallback_to_local`.

### Vector backends (`vector_backend`)

| Value | Dependency | Persistence |
|-------|------------|---------------|
| `local` | stdlib only | In-process token overlap (default). |
| `chroma` | `chromadb>=0.5.0` (source: `pip install -e '.[chroma]'`; GitHub wheel: `pip install 'hm_arch-*.whl[chroma]'`; after PyPI approval: `pip install 'hm-arch[chroma]'` — see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)) | `chroma_persist_directory` or `{db_parent}/chroma`; collections `{chroma_collection_prefix}_l2_episodic` and `{prefix}_l3_semantic`. SQLite remains the source of truth; L2/L3 rebuild vector indexes from SQLite on startup. |

### Protocols (`hm_arch.providers`)

Advanced integrations may use:

- `LLMProviderProtocol` — `score_importance`, `extract_semantic_triples`
- `EmbeddingProviderProtocol` — `embed`
- `resolve_llm_provider`, `resolve_embedding_provider`, `create_vector_store`

Failures with fallback disabled raise `ProviderRuntimeError` or `ProviderConfigurationError`.

---

## `EventType`

| Member | Value |
|--------|-------|
| `CONVERSATION` | `conversation` |
| `OBSERVATION` | `observation` |
| `DECISION` | `decision` |
| `ERROR` | `error` |
| `CODE` | `code` |
| `TASK` | `task` |
| `SYSTEM` | `system` |

---

## `MemoryReceipt`

Returned by `HMArch.add()`.

Confirmation returned by :py:meth:`HMArch.add`.

Attributes
----------
memory_id:
    Unique identifier for the persisted memory.
layer:
    Integer layer index where the memory was stored (0=L0 … 3=L3).
importance:
    Computed importance score in ``[0, 1]``.
initial_strength:
    Initial memory strength (retention) at insertion time.
decay_estimate:
    Predicted retention at key future checkpoints, e.g.
    ``{"1d": 0.92, "7d": 0.65, "30d": 0.28}``.
consolidation_scheduled:
    When the memory is next scheduled for consolidation review.
provenance:
    Optional origin metadata captured at insertion time.
sensitive_filter:
    Safe diagnostics when sensitive-data filtering modified the stored
    content (category counts only, never secret values).

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | `'str'` ||
| `layer` | `'int'` ||
| `importance` | `'float'` ||
| `initial_strength` | `'float'` ||
| `decay_estimate` | `'dict'` ||
| `consolidation_scheduled` | `'datetime'` ||
| `provenance` | `'MemoryProvenance | None'` ||
| `sensitive_filter` | `'dict | None'` ||

---

## `MemoryItem`

Single hit inside `SearchResult.results`.

A single memory record returned inside a :class:`SearchResult`.

Attributes
----------
memory_id:
    Unique identifier.
layer:
    Integer layer index (0–3).
content:
    Raw text content of the memory.
retention:
    Current retention value in ``[0, 1]``.
relevance:
    Query-relevance score in ``[0, 1]``.
score:
    Combined ranking score (``retention * relevance * layer_priority``).
metadata:
    Arbitrary extra fields stored alongside the memory.
provenance:
    Optional origin metadata for cross-agent recall and filtering.

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | `'str'` ||
| `layer` | `'int'` ||
| `content` | `'str'` ||
| `retention` | `'float'` ||
| `relevance` | `'float'` ||
| `score` | `'float'` ||
| `metadata` | `'dict'` | (factory)|
| `provenance` | `'MemoryProvenance | None'` ||

---

## `SearchResult`

Returned by `HMArch.search()`.

Wrapper returned by :py:meth:`HMArch.search`.

Individual hits are carried in :attr:`results` as :class:`MemoryItem`
objects.  The wrapper also exposes diagnostic metadata about the search
itself.

Attributes
----------
results:
    Ranked list of matching memory items.
total_scanned:
    Total number of candidates examined before scoring.
timing_ms:
    Wall-clock time spent on the search in milliseconds.
source_breakdown:
    Number of candidates considered per layer, keyed by integer layer
    index, e.g. ``{0: 5, 1: 12, 2: 40, 3: 8}``.

| Field | Type | Description |
|-------|------|-------------|
| `results` | `'list[MemoryItem]'` ||
| `total_scanned` | `'int'` ||
| `timing_ms` | `'float'` ||
| `source_breakdown` | `'dict[int, int]'` ||

---

## `ConsolidationReport`

Returned by `HMArch.consolidate()`.

Summary returned by :py:meth:`HMArch.consolidate`.

Attributes
----------
extracted_semantics:
    Number of semantic triples extracted from episodic memories.
merged_duplicates:
    Number of duplicate entries merged during the cycle.
resolved_conflicts:
    Number of conflicting semantic facts superseded.
archived_to_l4:
    Number of memories promoted to the L4 compressed archive.
scheduled_reviews:
    Number of memories added to the review queue.
marked_deletable:
    Number of memories flagged for future physical deletion.
duration_seconds:
    Wall-clock time taken for the consolidation cycle.

| Field | Type | Description |
|-------|------|-------------|
| `extracted_semantics` | `'int'` ||
| `merged_duplicates` | `'int'` ||
| `resolved_conflicts` | `'int'` ||
| `archived_to_l4` | `'int'` ||
| `scheduled_reviews` | `'int'` ||
| `marked_deletable` | `'int'` ||
| `duration_seconds` | `'float'` ||

---

## `RetentionCurve`

Returned by `HMArch.get_retention_curve()`.

Predicted retention curve returned by :py:meth:`HMArch.get_retention_curve`.

Attributes
----------
days:
    Sorted list of day offsets at which retention was sampled.
retention:
    Retention values (in ``[0, 1]``) corresponding to each day in
    :attr:`days`.
review_suggested_at_day:
    Earliest day at which a review is recommended to maintain retention.
archive_at_day:
    Day at which retention drops below the archive threshold.

| Field | Type | Description |
|-------|------|-------------|
| `days` | `'list[int]'` ||
| `retention` | `'list[float]'` ||
| `review_suggested_at_day` | `'int'` ||
| `archive_at_day` | `'int'` ||

---

## `MemoryStats`

Returned by `HMArch.get_stats()`.

Aggregated statistics returned by :py:meth:`HMArch.get_stats`.

Attributes
----------
total_memories:
    Total number of active memories across all layers.
by_layer:
    Per-layer counts keyed by integer layer index (L6 counts persisted
    ``meta_memory`` rows under ``hm_arch.l6.*``).
storage_size_mb:
    On-disk storage used by the database in megabytes.
retention_distribution:
    Histogram or summary of current retention values, e.g.
    ``{"0-0.25": 12, "0.25-0.5": 30, "0.5-0.75": 45, "0.75-1.0": 60}``.
review_queue_length:
    Number of memories currently scheduled for review.
last_consolidation_at:
    Timestamp of the most recent consolidation cycle, or ``None`` if
    consolidation has not yet run.
archive_storage_mb:
    On-disk size of L4 gzip archives under the archive root, in megabytes.
sensitive_data_diagnostics:
    Cumulative safe filtering statistics (category counts only).

| Field | Type | Description |
|-------|------|-------------|
| `total_memories` | `'int'` ||
| `by_layer` | `'dict[int, int]'` ||
| `storage_size_mb` | `'float'` ||
| `retention_distribution` | `'dict'` ||
| `review_queue_length` | `'int'` ||
| `last_consolidation_at` | `'datetime | None'` ||
| `archive_storage_mb` | `'float'` | (default: `0.0`)|
| `sensitive_data_diagnostics` | `'dict'` | (factory)|

---

## `ForgetResult`

Returned by `HMArch.forget()`.

Result returned by :py:meth:`HMArch.forget`.

Attributes
----------
forgotten_count:
    Number of memories removed or marked deleted.
archived_count:
    Number of memories moved to the L4 archive instead of deleted.
freed_memory_mb:
    Approximate storage freed in megabytes.
affected_layers:
    List of integer layer indices from which memories were removed.
details:
    Per-memory detail records, each a dict with at least ``memory_id``
    and ``action`` (``"deleted"`` | ``"archived"``).

| Field | Type | Description |
|-------|------|-------------|
| `forgotten_count` | `'int'` ||
| `archived_count` | `'int'` ||
| `freed_memory_mb` | `'float'` ||
| `affected_layers` | `'list[int]'` ||
| `details` | `'list[dict]'` ||

---

## `ContextAwareScore`

PRD forgetting score decomposition.

Decomposed PRD forgetting score.

Raw factors are in ``[0, 1]``.  :attr:`composite` is the weighted PRD sum::

    Forgetting_Score =
        0.35 * (1 - R)
      + 0.25 * (1 - Relevance)
      + 0.15 * Redundancy
      + 0.15 * Contradiction
      + 0.10 * Privacy

Higher :attr:`composite` means the memory is more eligible for forgetting.

| Field | Type | Description |
|-------|------|-------------|
| `retention` | `'float'` ||
| `relevance` | `'float'` ||
| `redundancy` | `'float'` ||
| `contradiction` | `'float'` ||
| `privacy` | `'float'` ||
| `composite` | `'float'` ||

---

## Forgetting lifecycle (`hm_arch.forgetting`)

| Name | Kind |
|------|------|
| `TimeProvider` | protocol |
| `SystemTimeProvider` | class |
| `ManualTimeProvider` | class |
| `ForgettingController` | class |
| `ContextAwareScore` | dataclass |

Operational automatic lifecycle for consolidation and cleanup.

* When ``config.auto_consolidate`` is enabled, runs consolidation once
  every ``config.consolidate_interval_hours`` (measured by
  :class:`TimeProvider`, not wall-clock sleeps).
* Performs conservative physical cleanup only for ``deletable`` rows whose
  ``deletable_at`` timestamp is older than
  ``config.deletion_safety_period_hours`` **and** whose PRD forgetting
  score meets ``config.forgetting_score_threshold``.
* Populates retention, relevance, redundancy, contradiction, and privacy
  from stored data when evaluating lifecycle candidates.

### `TimeProvider`

Return the current UTC time for retention and lifecycle scheduling.

```python
class TimeProvider:
    def now(self) -> datetime: ...
```

### `ManualTimeProvider`

Controllable clock for offline lifecycle tests.

Tests advance time with :meth:`advance` instead of sleeping or mutating
stored timestamps.

### PRD forgetting score

The context-aware forgetting score is:

```
Forgetting_Score =
    0.35 * (1 - R)
  + 0.25 * (1 - Relevance)
  + 0.15 * Redundancy
  + 0.15 * Contradiction
  + 0.10 * Privacy
```

`HMArch.forget(memory_id=None)` applies this score during the global scan.
Automated physical cleanup waits for `deletion_safety_period_hours`.

### Memory strength modulation (HM-29)

PRD multiplicative initial strength (offline, deterministic):

```
S = S_base * I_mod * E_mod * R_mod * C_mod
```

* ``S_base = 0.5``
* ``I_mod`` in ``[1.0, 2.0]`` from importance ``[0, 1]``
* ``E_mod`` in ``[0.8, 1.5]`` from emotion ``[0, 1]``
* ``R_mod`` in ``[1.0, 3.0]``: ``1.0 + 0.3 * (encode_repetitions + successful_retrievals)``
* ``C_mod`` in ``[0.5, 1.5]`` (neutral ``1.0``, consistent ``1.5``, superseded conflict ``0.5``)

Maximum product (before clamp): ``6.75``. ``MemoryConfig.strength_min``, ``strength_max``, ``retrieval_reinforcement_increment``, and ``retrieval_relevance_threshold`` control bounds and retrieval reinforcement.

Retention scales as ``R(t) = min(1.0, R_layer(t) * S)``. At encode, ``current_retention = min(1.0, S)`` while ``initial_strength`` keeps the full PRD multiplier. Each successful search reinforces each underlying L2/L3 memory at most once (best relevance wins when L0/L1 and L2 share a link). Each successful retrieval increments ``successful_retrievals`` and recomputes ``S``.

Exported helpers include ``compute_initial_strength``, ``apply_retrieval_reinforcement``, ``StrengthFactors``, and modifier factor functions.

---

## Memory layers (`hm_arch.layers`)

Advanced layer APIs (offline tests cover these modules):

| Class | Role |
|-------|------|
| `L0SensoryRegister` | Bounded sensory window |
| `L1WorkingMemory` | Session working memory |
| `L2EpisodicBuffer` | Durable episodic buffer (SQLite) |
| `L3SemanticMemory` | Semantic triple store |
| `L4EpisodicLTM` | Gzip episodic archive |
| `L5ProceduralMemory` | Procedural skills |
| `L6MetaMemory` | Usage tracking and meta policies |

Supporting types: `LayerItem`, `EpisodicItem`, `SemanticFact`,
`ArchivedEpisodic`, `SkillRecord`, `HotMemoryRecord`, `StrategyPlan`.

Full export list: `BaseLayer, LayerItem, L0SensoryRegister, L1WorkingMemory, EpisodicItem, L2EpisodicBuffer, SemanticFact, L3SemanticMemory, ArchivedEpisodic, L4EpisodicLTM, L5ProceduralMemory, SkillRecord, L6MetaMemory, HotMemoryRecord, StrategyPlan`.

