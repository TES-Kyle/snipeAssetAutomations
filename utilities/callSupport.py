"""Helpers for calling automation functions that may or may not take an extra argument."""

import inspect
import logging

logger = logging.getLogger(__name__)


def call_with_optional_second_arg(func, first, second):
    """Call func(first, second) if it can accept two positional args, else func(first).

    Decided from the function's signature up front -- not by calling it and
    catching TypeError, which would re-run the function (and repeat any
    side effects) whenever a TypeError is raised from inside its body.

    Args:
        func: The automation function to call.
        first: Always passed (the asset tag).
        second: Passed only if func accepts a second positional argument.

    Returns:
        Whatever func returns.
    """
    try:
        inspect.signature(func).bind(first, second)
    except (TypeError, ValueError):
        logger.debug("call_with_optional_second_arg: %s takes one argument", getattr(func, "__name__", func))
        return func(first)
    return func(first, second)
