#!/usr/bin/env python3
"""Sync version-pinned tau2-bench retail/airline data into fixtures/.

Copies the smallest licensed subset needed for the HM-76 comparison:
policy, split metadata, ``base``-split tasks (default 3 per domain), and a
pruned ``db.json`` containing only entities referenced by those tasks.

Usage::

    python3 scripts/sync_tau2_bench_data.py
    python3 scripts/sync_tau2_bench_data.py --num-tasks 3 --version v1.0.0
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TAU2_BENCH_VERSION = "v1.0.0"
TAU2_BENCH_COMMIT = "17e07b1da2bbc0cadfddeea36412686e0604127b"
DEFAULT_TASK_SPLIT = "base"
DEFAULT_NUM_TASKS = 3
BUNDLED_DATA_ROOT = _ROOT / "fixtures" / "tau2-bench" / TAU2_BENCH_VERSION / "data"


def bundled_domain_dir(domain: str) -> Path:
    return BUNDLED_DATA_ROOT / "tau2" / "domains" / domain

_REPO = "https://github.com/sierra-research/tau2-bench.git"
_DOMAINS = ("retail", "airline")
_STATIC_FILES = ("policy.md", "split_tasks.json")


def _clone_repo(target: Path, version: str) -> None:
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", version, _REPO, str(target)],
        check=True,
    )


def _collect_values(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        text = value.strip()
        if text:
            refs.add(text)
    elif isinstance(value, dict):
        for item in value.values():
            refs.update(_collect_values(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_collect_values(item))
    return refs


def _task_reference_ids(task: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    criteria = task.get("evaluation_criteria") or {}
    for action in criteria.get("actions") or []:
        refs.update(_collect_values(action.get("arguments") or {}))
    scenario = task.get("user_scenario") or {}
    refs.update(_collect_values(scenario))
    return refs


def _filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    task_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = set(task_ids)
    return [task for task in tasks if str(task.get("id")) in wanted]


def _users_for_tasks(tasks: list[dict[str, Any]], db: dict[str, Any]) -> set[str]:
    users = db.get("users") or {}
    matched: set[str] = set()
    for task in tasks:
        for action in (task.get("evaluation_criteria") or {}).get("actions") or []:
            if action.get("name") != "find_user_id_by_name_zip":
                continue
            args = action.get("arguments") or {}
            first = str(args.get("first_name", "")).strip().lower()
            last = str(args.get("last_name", "")).strip().lower()
            zip_code = str(args.get("zip", "")).strip()
            for user_id, user in users.items():
                name = user.get("name") or {}
                address = user.get("address") or {}
                if (
                    str(name.get("first_name", "")).strip().lower() == first
                    and str(name.get("last_name", "")).strip().lower() == last
                    and str(address.get("zip", "")).strip() == zip_code
                ):
                    matched.add(user_id)
    return matched


def _known_info_user_ids(tasks: list[dict[str, Any]]) -> set[str]:
    import re

    pattern = re.compile(r"user id is ([a-z0-9_]+)", re.IGNORECASE)
    refs: set[str] = set()
    for task in tasks:
        scenario = task.get("user_scenario") or {}
        instructions = scenario.get("instructions") or {}
        known_info = str(instructions.get("known_info") or "")
        refs.update(pattern.findall(known_info))
    return refs


def _prune_db(
    db: dict[str, Any],
    tasks: list[dict[str, Any]],
    seed_refs: set[str],
    *,
    domain: str,
) -> dict[str, Any]:
    refs = set(seed_refs)
    refs.update(_known_info_user_ids(tasks))

    if domain == "airline":
        reservations = db.get("reservations") or {}
        flights = db.get("flights") or {}
        users = db.get("users") or {}

        kept_reservations = {
            key: value
            for key, value in reservations.items()
            if key in refs or str(value.get("reservation_id")) in refs
        }
        for reservation in kept_reservations.values():
            refs.update(
                {
                    str(reservation.get("reservation_id")),
                    str(reservation.get("user_id")),
                }
            )
            refs.update(_collect_values(reservation.get("flights") or []))
            refs.update(_collect_values(reservation.get("passengers") or []))

        kept_flights = {
            key: value
            for key, value in flights.items()
            if key in refs or str(value.get("flight_id")) in refs
        }
        kept_users = {
            key: value
            for key, value in users.items()
            if key in refs or str(value.get("user_id")) in refs
        }
        return {
            **{
                key: value
                for key, value in db.items()
                if key not in {"flights", "reservations", "users"}
            },
            "flights": kept_flights,
            "reservations": kept_reservations,
            "users": kept_users,
        }

    orders = db.get("orders") or {}
    users = db.get("users") or {}
    products = db.get("products") or {}

    for order_id, order in orders.items():
        if order_id in refs or str(order.get("order_id")) in refs:
            refs.update({order_id, str(order.get("order_id")), str(order.get("user_id"))})
            refs.update(_collect_values(order.get("items") or []))

    refs.update(_users_for_tasks(tasks, db))

    kept_orders = {
        key: value
        for key, value in orders.items()
        if key in refs or str(value.get("order_id")) in refs
    }
    kept_order_ids = set(kept_orders) | {
        str(order.get("order_id")) for order in kept_orders.values()
    }

    kept_users: dict[str, Any] = {}
    for user_id, user in users.items():
        if user_id not in refs and str(user.get("user_id")) not in refs:
            continue
        trimmed = dict(user)
        trimmed_orders = [
            order_id
            for order_id in (user.get("orders") or [])
            if order_id in kept_order_ids
        ]
        trimmed["orders"] = trimmed_orders
        kept_users[user_id] = trimmed
        refs.update(_collect_values(user.get("payment_methods") or {}))

    kept_products = {}
    for product_id, product in products.items():
        product_refs = {product_id, str(product.get("product_id"))}
        for variant in (product.get("variants") or {}).values():
            product_refs.update(_collect_values(variant))
        if refs.intersection(product_refs):
            kept_products[product_id] = product

    return {
        **{key: value for key, value in db.items() if key not in {"products", "users", "orders"}},
        "products": kept_products,
        "users": kept_users,
        "orders": kept_orders,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def sync_domain(
    checkout: Path,
    domain: str,
    *,
    task_split_name: str,
    num_tasks: int,
) -> dict[str, int]:
    src = checkout / "data" / "tau2" / "domains" / domain
    dst = bundled_domain_dir(domain)
    dst.mkdir(parents=True, exist_ok=True)

    for name in _STATIC_FILES:
        shutil.copy2(src / name, dst / name)

    split_tasks = _load_json(src / "split_tasks.json")
    task_ids = list(split_tasks.get(task_split_name) or [])[:num_tasks]
    if not task_ids:
        raise ValueError(
            f"No tasks found for split {task_split_name!r} in domain {domain!r}"
        )

    all_tasks = _load_json(src / "tasks.json")
    filtered_tasks = _filter_tasks(all_tasks, task_ids=task_ids)
    if len(filtered_tasks) != len(task_ids):
        missing = set(task_ids) - {str(task["id"]) for task in filtered_tasks}
        raise ValueError(f"Missing tasks in {domain}: {sorted(missing)}")

    seed_refs: set[str] = set()
    for task in filtered_tasks:
        seed_refs.update(_task_reference_ids(task))

    full_db = _load_json(src / "db.json")
    pruned_db = _prune_db(full_db, filtered_tasks, seed_refs, domain=domain)

    _write_json(dst / "tasks.json", filtered_tasks)
    _write_json(dst / "db.json", pruned_db)

    return {
        "tasks": len(filtered_tasks),
        "products": len(pruned_db.get("products") or {}),
        "users": len(pruned_db.get("users") or {}),
        "orders": len(pruned_db.get("orders") or {}),
    }


def sync_data(
    *,
    version: str = TAU2_BENCH_VERSION,
    source: Path | None = None,
    task_split_name: str = DEFAULT_TASK_SPLIT,
    num_tasks: int = DEFAULT_NUM_TASKS,
) -> Path:
    checkout = source
    temp_dir: Path | None = None
    if checkout is None:
        temp_dir = _ROOT / ".cache" / f"tau2-bench-{version}"
        _clone_repo(temp_dir, version)
        checkout = temp_dir

    stats: dict[str, dict[str, int]] = {}
    for domain in _DOMAINS:
        stats[domain] = sync_domain(
            checkout,
            domain,
            task_split_name=task_split_name,
            num_tasks=num_tasks,
        )

    if temp_dir is not None:
        shutil.rmtree(temp_dir, ignore_errors=True)

    manifest = {
        "tau2_bench_version": version,
        "tau2_bench_commit": TAU2_BENCH_COMMIT,
        "task_split": task_split_name,
        "num_tasks": num_tasks,
        "domains": stats,
    }
    _write_json(BUNDLED_DATA_ROOT / "manifest.json", manifest)
    return BUNDLED_DATA_ROOT


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=TAU2_BENCH_VERSION)
    parser.add_argument("--task-split", default=DEFAULT_TASK_SPLIT)
    parser.add_argument("--num-tasks", type=int, default=DEFAULT_NUM_TASKS)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Existing tau2-bench checkout (skips git clone)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = sync_data(
        version=args.version,
        source=args.source,
        task_split_name=args.task_split,
        num_tasks=args.num_tasks,
    )
    print(
        f"Synced tau2-bench {args.version} ({TAU2_BENCH_COMMIT}) into {root} "
        f"split={args.task_split} num_tasks={args.num_tasks}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
