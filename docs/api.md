# HM-Arch API reference

_Generated from `hm_arch` v0.1.0. Regenerate with `python scripts/generate_api_docs.py`._

Stable integrations should import from the top-level package:

```python
from hm_arch import HMArch, MemoryConfig, EventType
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

Initialize self.  See help(type(self)) for accurate signature.

```python
HMArch.__init__(self, db_path: 'str' = './.agent_memory.db', config: 'Optional[MemoryConfig]' = None) -> 'None'
```

### `HMArch.add`

Store *content* in working memory (L1) and the episodic buffer (L2).

``add()`` always succeeds without an external LLM key.  L3 semantic
extraction is **not** triggered here; it happens during
``consolidate()`` (a later milestone).

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

Returns
-------
MemoryReceipt
    Confirmation including the ``memory_id`` assigned by L2, which
    is the durable database-backed identifier for the event.

```python
HMArch.add(self, content: 'str', event_type: 'EventType' = <EventType.CONVERSATION: 'conversation'>, metadata: 'Optional[dict]' = None, importance: 'Optional[float]' = None) -> 'MemoryReceipt'
```

### `HMArch.search`

Return the top-*k* memories most relevant to *query*.

Queries L1 working memory, L2 episodic buffer, L3 semantic memory, and
L4 archived episodic memories.  Candidates from all layers are merged,
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
    When ``None``, all supported layers ``(1, 2, 3, 4)`` are queried.

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

Forget one memory or run a global deletable-memory scan.

When *memory_id* is provided, only that memory is considered.  When
``memory_id`` is ``None``, every row with ``status='deletable'`` is
processed (and, when *force* is ``True``, active rows below the layer
delete threshold are included as well).

L2 memories below the archive threshold are moved to L4 when possible;
otherwise they are marked ``deleted``.  Archived L4 rows purge the gzip
artifact.  L3 rows are marked ``deleted`` and removed from the vector
index.

Parameters
----------
memory_id:
    Target memory identifier, or ``None`` for a global scan.
force:
    When ``True``, forget eligible memories even if they are still
    ``active`` (below the layer delete threshold).  When ``False``,
    only ``deletable`` rows (or a single memory below threshold) are
    affected.

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

Counts include in-session L1 items plus persisted L2/L3 rows with
``status = 'active'``.  Retention histogram buckets are computed from
``memory_index.current_retention`` for all active persisted memories.

```python
HMArch.get_stats(self) -> 'MemoryStats'
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
| `replay_sample_ratio` | `'float'` | (default: `0.2`)|
| `max_memories_l2` | `'int'` | (default: `100000`)|
| `max_memories_l3` | `'int'` | (default: `50000`)|
| `max_skills_l5` | `'int'` | (default: `10000`)|
| `llm_provider` | `'str'` | (default: `'deepseek'`)|
| `llm_model` | `'str'` | (default: `'deepseek-v4-flash'`)|
| `llm_api_key` | `'Optional[str]'` ||
| `llm_base_url` | `'Optional[str]'` ||
| `embedding_provider` | `'str'` | (default: `'deepseek'`)|
| `embedding_model` | `'str'` | (default: `'deepseek-v4-flash'`)|
| `embedding_dim` | `'int'` | (default: `1536`)|
| `layer_priorities` | `'dict[str, float]'` | (factory)|

### Presets

`MemoryConfig.preset(name)` — `name` is one of:

- `code_agent`
- `chat_agent`
- `research_agent`

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

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | `'str'` ||
| `layer` | `'int'` ||
| `importance` | `'float'` ||
| `initial_strength` | `'float'` ||
| `decay_estimate` | `'dict'` ||
| `consolidation_scheduled` | `'datetime'` ||

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

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | `'str'` ||
| `layer` | `'int'` ||
| `content` | `'str'` ||
| `retention` | `'float'` ||
| `relevance` | `'float'` ||
| `score` | `'float'` ||
| `metadata` | `'dict'` | (factory)|

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
    Per-layer counts keyed by integer layer index.
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

| Field | Type | Description |
|-------|------|-------------|
| `total_memories` | `'int'` ||
| `by_layer` | `'dict[int, int]'` ||
| `storage_size_mb` | `'float'` ||
| `retention_distribution` | `'dict'` ||
| `review_queue_length` | `'int'` ||
| `last_consolidation_at` | `'datetime | None'` ||

---

## `ForgetResult`

Type for future `forget()` API; exported for contract stability.

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

