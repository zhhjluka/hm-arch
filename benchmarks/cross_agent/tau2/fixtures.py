"""tau2-bench retail and airline fixtures (HM-76 / MEM-76)."""

from __future__ import annotations

from ..types import SyntheticFixture
from .config import Tau2ComparisonMode, Tau2Domain
from .loader import load_real_domain_fixture
from .smoke_fixtures import SMOKE_FIXTURE_LABEL, get_smoke_domain_fixture


def get_tau2_domain_fixture(
    domain: Tau2Domain,
    *,
    mode: Tau2ComparisonMode = Tau2ComparisonMode.SMOKE,
    num_tasks: int | None = None,
) -> SyntheticFixture:
    if mode is Tau2ComparisonMode.SMOKE:
        return get_smoke_domain_fixture(domain)
    fixture, _executions = load_real_domain_fixture(
        domain,
        num_tasks=num_tasks or 3,
    )
    return fixture


def retail_fixture() -> SyntheticFixture:
    return get_smoke_domain_fixture(Tau2Domain.RETAIL)


def airline_fixture() -> SyntheticFixture:
    return get_smoke_domain_fixture(Tau2Domain.AIRLINE)


__all__ = [
    "SMOKE_FIXTURE_LABEL",
    "airline_fixture",
    "get_tau2_domain_fixture",
    "retail_fixture",
]
