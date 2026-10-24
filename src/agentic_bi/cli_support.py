"""Shared boundary handling for the console entry points.

Every ``agentic-bi-*`` command must end on a documented exit code, never on an
unhandled traceback:

* ``0`` — success;
* ``1`` — a runtime failure (the work ran and its own result was negative);
* ``2`` — a bad input or configuration (missing/unreadable file, unsupported
  format, invalid spec).

`run_boundary` wraps a command body so an expected, user-facing failure becomes a
short message on stderr plus a code. An unexpected error is **not** swallowed:
it stays a traceback, because it is a bug in the framework, not a user mistake.

Public API:
    EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT
    run_boundary(body, prog) -> int
"""

from __future__ import annotations

import sys
from collections.abc import Callable

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2

# Failures that mean "the input was wrong", not "the framework is broken": a
# missing/unreadable path, a value the parser rejects, or an unsupported format.
_INPUT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    NotImplementedError,
)


def run_boundary(body: Callable[[], int], *, prog: str) -> int:
    """Run a command body, mapping an input failure to exit code 2.

    Args:
        body: the command's real work; returns its exit code (0 or 1).
        prog: the program name, used to prefix the error message.

    Returns:
        The body's code on success, or ``EXIT_BAD_INPUT`` (2) when the input is
        missing, unreadable or unsupported.
    """
    try:
        return body()
    except _INPUT_ERRORS as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


def fail(prog: str, message: str, code: int = EXIT_BAD_INPUT) -> int:
    """Print `message` to stderr and return `code` (for pre-flight checks)."""
    print(f"{prog}: error: {message}", file=sys.stderr)
    return code


__all__ = ["EXIT_OK", "EXIT_FAILED", "EXIT_BAD_INPUT", "fail", "run_boundary"]
