"""Compatibility shim for logging.

Some modules import `setup_logging` from `libs.logging`, while the implementation
lives in `libs.common.logging`. This wrapper keeps backward compatibility.
"""

from __future__ import annotations

from libs.common.logging import setup_logging

__all__ = ["setup_logging"]
