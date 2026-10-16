"""Tests for utilities.callSupport (pure logic)."""

import pytest

from utilities.callSupport import call_with_optional_second_arg


def test_passes_second_arg_when_function_accepts_it():
    assert call_with_optional_second_arg(lambda a, b: (a, b), "1234", ["x"]) == ("1234", ["x"])


def test_passes_second_arg_to_varargs_functions():
    def f(tag, *args):
        return (tag, args)
    assert call_with_optional_second_arg(f, "1234", ["x"]) == ("1234", (["x"],))


def test_drops_second_arg_for_single_argument_functions():
    assert call_with_optional_second_arg(lambda a: a, "1234", ["x"]) == "1234"


def test_a_typeerror_raised_inside_the_function_is_not_retried():
    calls = []

    def f(tag, extra):
        calls.append(tag)
        raise TypeError("bug inside the function")

    with pytest.raises(TypeError):
        call_with_optional_second_arg(f, "1234", ["x"])
    assert calls == ["1234"]  # ran exactly once
