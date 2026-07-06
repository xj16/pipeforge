"""Core primitives for data-quality checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import pandas as pd


class Severity(str, Enum):
    """How much a failed check matters."""

    ERROR = "error"  # Blocks the run when fail_on_check_error is set.
    WARNING = "warning"  # Recorded, never blocks.


@dataclass
class CheckResult:
    """Outcome of a single data-quality check."""

    name: str
    passed: bool
    severity: Severity
    observed: float
    threshold: float
    detail: str = ""

    @property
    def is_blocking(self) -> bool:
        return (not self.passed) and self.severity is Severity.ERROR

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity.value,
            "observed": self.observed,
            "threshold": self.threshold,
            "detail": self.detail,
        }


# A check is a function: DataFrame -> CheckResult.
CheckFn = Callable[[pd.DataFrame], CheckResult]


@dataclass
class CheckSuite:
    """A named collection of checks run against one DataFrame."""

    name: str
    checks: list[CheckFn] = field(default_factory=list)

    def add(self, check: CheckFn) -> "CheckSuite":
        self.checks.append(check)
        return self

    def run(self, df: pd.DataFrame) -> list[CheckResult]:
        return [check(df) for check in self.checks]

    @staticmethod
    def has_blocking_failure(results: list[CheckResult]) -> bool:
        return any(r.is_blocking for r in results)

    @staticmethod
    def summarize(results: list[CheckResult]) -> str:
        lines = []
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(
                f"  [{status}] {r.name} "
                f"(observed={r.observed}, threshold={r.threshold}, {r.severity.value})"
                + (f" -- {r.detail}" if r.detail and not r.passed else "")
            )
        return "\n".join(lines)
