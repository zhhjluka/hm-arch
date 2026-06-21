"""LoCoMo QA category mapping (official evaluation code order).

See snap-research/locomo ``task_eval/evaluation.py`` — category IDs in
``locomo10.json`` do not follow the prose order in the paper.
"""

from __future__ import annotations

LOCOMO_CATEGORY_NAMES: dict[int, str] = {
    1: "multi_hop",
    2: "temporal",
    3: "open_domain",
    4: "single_hop",
    5: "adversarial",
}


def category_name(category_id: int) -> str:
    """Return the canonical category label for *category_id*."""
    try:
        return LOCOMO_CATEGORY_NAMES[category_id]
    except KeyError as exc:
        raise ValueError(f"Unknown LoCoMo category id: {category_id}") from exc
