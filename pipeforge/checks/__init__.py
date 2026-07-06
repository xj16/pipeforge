"""Lightweight, dependency-free data-quality checks.

This is a small home-grown validation layer (think a miniature Great
Expectations) so pipeforge stays free and easy to install. Each check
returns a :class:`CheckResult`; a :class:`CheckSuite` runs many and
aggregates the outcome.
"""
from .core import CheckResult, CheckSuite, Severity
from .quality import build_default_suite

__all__ = ["CheckResult", "CheckSuite", "Severity", "build_default_suite"]
