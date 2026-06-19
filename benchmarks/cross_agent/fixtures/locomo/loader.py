"""Versioned LoCoMo dataset ingestion for the cross-agent harness."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...types import BenchmarkFamily, BenchmarkQuery, IngestItem, SyntheticFixture
from .categories import category_name

_DATA_DIR = Path(__file__).resolve().parent / "data"
_MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


@dataclass(frozen=True)
class LoCoMoDatasetManifest:
    """Pinned dataset metadata for reproducible ingestion."""

    dataset_id: str
    version: str
    description: str
    source_url: str
    filename: str
    sha256: str | None
    conversation_count: int | None
    qa_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "description": self.description,
            "source_url": self.source_url,
            "filename": self.filename,
            "sha256": self.sha256,
            "conversation_count": self.conversation_count,
            "qa_count": self.qa_count,
        }


class LoCoMoDatasetError(ValueError):
    """Raised when dataset files fail validation."""


def _load_manifest_file() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def get_dataset_manifest(dataset_id: str) -> LoCoMoDatasetManifest:
    """Return manifest metadata for *dataset_id*."""
    datasets = _load_manifest_file().get("datasets", {})
    if dataset_id not in datasets:
        known = ", ".join(sorted(datasets))
        raise LoCoMoDatasetError(
            f"Unknown LoCoMo dataset_id {dataset_id!r}; known: {known or '(none)'}"
        )
    row = datasets[dataset_id]
    return LoCoMoDatasetManifest(
        dataset_id=dataset_id,
        version=row["version"],
        description=row["description"],
        source_url=row["source_url"],
        filename=row["filename"],
        sha256=row.get("sha256"),
        conversation_count=row.get("conversation_count"),
        qa_count=row.get("qa_count"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_dataset_path(dataset_id: str) -> Path:
    manifest = get_dataset_manifest(dataset_id)
    path = _DATA_DIR / manifest.filename
    if not path.is_file():
        raise LoCoMoDatasetError(
            f"LoCoMo dataset file missing for {dataset_id!r}: {path}"
        )
    if manifest.sha256 is not None:
        actual = sha256_file(path)
        if actual != manifest.sha256:
            raise LoCoMoDatasetError(
                f"LoCoMo dataset checksum mismatch for {dataset_id!r}: "
                f"expected {manifest.sha256}, got {actual}"
            )
    return path


def _session_keys(conversation: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in conversation
        if re.fullmatch(r"session_\d+", key) is not None
    )


def _format_turn_content(
    *,
    speaker: str,
    text: str,
    dia_id: str,
    session_label: str,
    session_datetime: str | None,
) -> str:
    when = f" ({session_datetime})" if session_datetime else ""
    return f"[{session_label}{when}] {speaker} ({dia_id}): {text}"


def _normalize_answer(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    return text or None


def load_locomo_records(
    dataset_id: str,
    *,
    max_conversations: int | None = None,
) -> list[dict[str, Any]]:
    """Load raw LoCoMo conversation records from a versioned dataset file."""
    path = resolve_dataset_path(dataset_id)
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise LoCoMoDatasetError(f"Expected top-level JSON array in {path}")
    if max_conversations is not None and max_conversations > 0:
        return records[:max_conversations]
    return records


def load_locomo_fixture(
    dataset_id: str,
    dataset_version: str | None = None,
    *,
    max_conversations: int | None = None,
) -> SyntheticFixture:
    """Convert a versioned LoCoMo dataset file into harness ingest + query items."""
    manifest = get_dataset_manifest(dataset_id)
    if dataset_version is not None and dataset_version != manifest.version:
        raise LoCoMoDatasetError(
            f"Requested dataset_version {dataset_version!r} does not match "
            f"manifest version {manifest.version!r} for {dataset_id!r}"
        )

    ingest_items: list[IngestItem] = []
    queries: list[BenchmarkQuery] = []

    for conv_index, record in enumerate(
        load_locomo_records(dataset_id, max_conversations=max_conversations)
    ):
        conversation = record["conversation"]
        conv_id = f"conv-{conv_index}"
        session_keys = _session_keys(conversation)

        for session_key in session_keys:
            session_num = session_key.split("_", 1)[1]
            session_label = f"session-{session_num}"
            session_datetime = conversation.get(f"session_{session_num}_date_time")
            for turn in conversation[session_key]:
                dia_id = turn["dia_id"]
                text = turn.get("text", "").strip()
                if not text:
                    continue
                speaker = turn.get("speaker", "unknown")
                ingest_items.append(
                    IngestItem(
                        item_id=dia_id,
                        content=_format_turn_content(
                            speaker=speaker,
                            text=text,
                            dia_id=dia_id,
                            session_label=session_label,
                            session_datetime=session_datetime,
                        ),
                        session_id=f"{conv_id}:{session_label}",
                        metadata={
                            "speaker": speaker,
                            "dia_id": dia_id,
                            "conversation_id": conv_id,
                            "session": session_label,
                            "session_datetime": session_datetime,
                            "dataset_id": dataset_id,
                            "dataset_version": manifest.version,
                        },
                    )
                )

        for qa_index, qa in enumerate(record.get("qa", [])):
            category_id = int(qa["category"])
            evidence = tuple(str(item) for item in qa.get("evidence", ()))
            if category_id == 5:
                expected_answer = None
            else:
                expected_answer = _normalize_answer(qa.get("answer"))

            queries.append(
                BenchmarkQuery(
                    query_id=f"{conv_id}-q{qa_index}",
                    question=str(qa["question"]),
                    expected_answer=expected_answer,
                    expected_memory_ids=evidence,
                    metadata={
                        "category": category_id,
                        "category_name": category_name(category_id),
                        "conversation_id": conv_id,
                        "evidence": evidence,
                        "adversarial_answer": qa.get("adversarial_answer"),
                        "dataset_id": dataset_id,
                        "dataset_version": manifest.version,
                        "unanswerable": category_id == 5,
                    },
                )
            )

    return SyntheticFixture(
        family=BenchmarkFamily.LOCOMO,
        ingest_items=tuple(ingest_items),
        queries=tuple(queries),
        consolidate_after_ingest=True,
    )
