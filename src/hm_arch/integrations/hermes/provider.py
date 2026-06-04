"""Hermes Agent native Memory Provider lifecycle adapter for HM-Arch."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from hm_arch import EventType, HMArch
from hm_arch.integrations.common import (
    build_turn_start_context,
    record_turn_end,
    run_idle_consolidation,
)
from hm_arch.integrations.config import IntegrationConfig

from .config import HM_ARCH_PROVIDER_NAME, resolve_db_path
from .messages import iter_turn_pairs, summarize_messages_for_compression

logger = logging.getLogger(__name__)

_SEARCH_SCHEMA = {
    "name": "hm_arch_search",
    "description": (
        "Search HM-Arch durable memory (episodic and semantic layers) for "
        "facts relevant to the current task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query."},
            "top_k": {
                "type": "integer",
                "description": "Maximum number of hits to return (default 5).",
            },
        },
        "required": ["query"],
    },
}

_REMEMBER_SCHEMA = {
    "name": "hm_arch_remember",
    "description": "Store an explicit fact or preference in HM-Arch durable memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Fact or preference to store."},
            "importance": {
                "type": "number",
                "description": "Importance score in [0, 1] (default 0.7).",
            },
        },
        "required": ["content"],
    },
}


class HMArchHermesMemoryProvider:
    """Hermes-compatible memory provider backed by the HM-Arch SDK.

    Implements the lifecycle contract used by Hermes Agent's
    :class:`MemoryProvider` without importing Hermes at runtime, so offline
    tests can exercise recall, recording, compression saves, consolidation,
    and shutdown directly.
    """

    def __init__(
        self,
        integration: IntegrationConfig | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        self._integration = integration or IntegrationConfig()
        if db_path is not None:
            self._integration = IntegrationConfig(
                db_path=db_path,
                scope=self._integration.scope,
                recall_top_k=self._integration.recall_top_k,
                max_context_chars=self._integration.max_context_chars,
                auto_consolidate=self._integration.auto_consolidate,
                consolidate_on_idle=self._integration.consolidate_on_idle,
                replay_sample_ratio=self._integration.replay_sample_ratio,
            )
        self._memory: HMArch | None = None
        self._session_id = ""
        self._hermes_home = ""
        self._agent_context = "primary"
        self._prefetch_lock = threading.Lock()
        self._prefetched_context = ""
        self._sync_lock = threading.Lock()

    @property
    def name(self) -> str:
        return HM_ARCH_PROVIDER_NAME

    def is_available(self) -> bool:
        """Local SQLite storage is always available offline."""
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        """Open the configured HM-Arch database for the active Hermes session."""
        self.shutdown()
        self._session_id = session_id
        self._hermes_home = str(kwargs.get("hermes_home", "") or "")
        self._agent_context = str(kwargs.get("agent_context", "primary") or "primary")

        plugin_settings: Mapping[str, Any] = {}
        if self._hermes_home:
            from .config import load_hermes_config, read_plugin_settings

            config_path = Path(self._hermes_home) / "config.yaml"
            if config_path.exists():
                try:
                    loaded = load_hermes_config(config_path)
                    plugin_settings = read_plugin_settings(loaded)
                except Exception as exc:
                    logger.debug("Could not load Hermes config for HM-Arch: %s", exc)

        if self._integration.db_path:
            db_path = self._integration.resolve_db_path()
        elif self._hermes_home:
            db_path = resolve_db_path(self._hermes_home, plugin_settings)
        else:
            db_path = self._integration.resolve_db_path()

        memory_config = replace(self._integration.to_memory_config(), db_path=db_path)
        self._memory = HMArch(config=memory_config)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def system_prompt_block(self) -> str:
        if not self._memory:
            return ""
        return (
            "# HM-Arch Memory\n"
            "Active. Local SQLite-backed episodic and semantic memory with "
            "offline consolidation.\n"
            "Use hm_arch_search to recall durable facts and hm_arch_remember "
            "to store explicit preferences."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Return recalled context for the upcoming turn."""
        del session_id  # HM-Arch search is global per database file.
        with self._prefetch_lock:
            cached = self._prefetched_context
            self._prefetched_context = ""
        if cached:
            return cached
        return self._recall_context(query)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Warm recall for the next turn on a background thread."""
        del session_id

        def _run() -> None:
            try:
                context = self._recall_context(query)
                with self._prefetch_lock:
                    self._prefetched_context = context
            except Exception as exc:
                logger.debug("HM-Arch queue_prefetch failed (non-fatal): %s", exc)

        threading.Thread(target=_run, name="hm-arch-prefetch", daemon=True).start()

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Persist a completed turn without blocking the host agent."""
        del session_id, messages
        if self._agent_context != "primary":
            return
        if not user_content.strip() and not assistant_content.strip():
            return

        def _run() -> None:
            try:
                with self._sync_lock:
                    memory = self._require_memory()
                    record_turn_end(memory, user_content, assistant_content)
            except Exception as exc:
                logger.warning("HM-Arch sync_turn failed (non-fatal): %s", exc)

        threading.Thread(target=_run, name="hm-arch-sync", daemon=True).start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [_SEARCH_SCHEMA, _REMEMBER_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        memory = self._require_memory()
        try:
            if tool_name == "hm_arch_search":
                query = str(args.get("query", "")).strip()
                if not query:
                    return json.dumps({"error": "query is required"})
                top_k = int(args.get("top_k", self._integration.recall_top_k))
                hits = memory.search(query, top_k=max(1, top_k))
                return json.dumps(
                    {
                        "results": [
                            {
                                "memory_id": item.memory_id,
                                "content": item.content,
                                "layer": item.layer,
                                "score": item.score,
                                "retention": item.retention,
                            }
                            for item in hits.results
                        ],
                        "count": len(hits.results),
                    }
                )
            if tool_name == "hm_arch_remember":
                content = str(args.get("content", "")).strip()
                if not content:
                    return json.dumps({"error": "content is required"})
                importance = float(args.get("importance", 0.7))
                receipt = memory.add(
                    content,
                    event_type=EventType.CONVERSATION,
                    importance=importance,
                )
                return json.dumps(
                    {
                        "memory_id": receipt.memory_id,
                        "status": "stored",
                    }
                )
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Consolidate at session boundaries and flush remaining transcript."""
        if self._agent_context != "primary":
            return
        memory = self._memory
        if memory is None:
            return
        try:
            for user_message, agent_message in iter_turn_pairs(messages):
                record_turn_end(memory, user_message, agent_message)
            if self._integration.consolidate_on_idle:
                run_idle_consolidation(memory)
        except Exception as exc:
            logger.warning("HM-Arch on_session_end failed (non-fatal): %s", exc)

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs: Any,
    ) -> None:
        del parent_session_id, rewound, kwargs
        self._session_id = new_session_id
        if reset and self._memory is not None and self._integration.consolidate_on_idle:
            try:
                run_idle_consolidation(self._memory)
            except Exception as exc:
                logger.debug("HM-Arch on_session_switch consolidate failed: %s", exc)
        with self._prefetch_lock:
            self._prefetched_context = ""

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Save transcript snippets before Hermes discards compressed messages."""
        if self._agent_context != "primary":
            return ""
        memory = self._memory
        if memory is None:
            return ""
        try:
            summary = summarize_messages_for_compression(
                messages,
                max_chars=min(self._integration.max_context_chars, 4000),
            )
            if summary:
                memory.add(
                    f"Pre-compression transcript:\n{summary}",
                    event_type=EventType.OBSERVATION,
                    importance=0.75,
                )
            if self._integration.consolidate_on_idle:
                run_idle_consolidation(memory)
            return summary
        except Exception as exc:
            logger.debug("HM-Arch on_pre_compress failed (non-fatal): %s", exc)
            return ""

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        del metadata
        if action != "add" or not content.strip():
            return
        memory = self._memory
        if memory is None:
            return
        try:
            label = "User" if target == "user" else "Memory"
            memory.add(
                f"{label}: {content.strip()}",
                event_type=EventType.CONVERSATION,
                importance=0.8 if target == "user" else 0.7,
            )
        except Exception as exc:
            logger.debug("HM-Arch on_memory_write mirror failed: %s", exc)

    def get_config_schema(self) -> List[Dict[str, Any]]:
        default_db = "$HERMES_HOME/hm_arch_memory.db"
        return [
            {
                "key": "db_path",
                "description": "SQLite database path for HM-Arch durable memory",
                "default": default_db,
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        """Write plugin settings without overwriting unrelated providers."""
        from .config import load_hermes_config, merge_plugin_settings

        config_path = Path(hermes_home) / "config.yaml"
        existing = load_hermes_config(config_path) if config_path.exists() else {}
        merged = merge_plugin_settings(existing, values)
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required to save Hermes config.yaml files"
            ) from exc
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(merged, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def shutdown(self) -> None:
        """Close HM-Arch resources."""
        with self._prefetch_lock:
            self._prefetched_context = ""
        memory = self._memory
        self._memory = None
        if memory is not None:
            try:
                if self._integration.consolidate_on_idle:
                    run_idle_consolidation(memory)
            except Exception as exc:
                logger.debug("HM-Arch shutdown consolidation failed: %s", exc)
            memory.close()

    def _require_memory(self) -> HMArch:
        if self._memory is None:
            raise RuntimeError("HM-Arch Hermes provider is not initialized")
        return self._memory

    def _recall_context(self, query: str) -> str:
        query = query.strip()
        if not query:
            return ""
        memory = self._require_memory()
        context = build_turn_start_context(
            memory,
            query,
            top_k=self._integration.recall_top_k,
        )
        if len(context) <= self._integration.max_context_chars:
            return context
        return context[: self._integration.max_context_chars - 3].rstrip() + "..."
