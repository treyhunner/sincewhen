"""Tests for feature detection."""

import pytest

from sincewhen import Version, detect, minimum_version


def features(source):
    """The set of feature ids detected in a source snippet."""
    return {found.feature.id for found in detect(source)}


def test_no_features_detected():
    assert detect("x = 1") == []
    assert minimum_version("x = 1") is None


@pytest.mark.parametrize(
    "source, expected",
    [
        ("if (n := 10) > 5:\n    pass", "walrus"),
        ("f'{x}'", "f-string"),
        ("t'{x}'", "t-string"),
        ("match x:\n    case 1:\n        pass", "match-statement"),
        ("def f(a, /, b):\n    pass", "positional-only-parameters"),
        ("def f(*, a):\n    pass", "keyword-only-arguments"),
        ("def f[T](x: T) -> T:\n    return x", "type-parameters"),
        ("type Alias = int", "type-alias-statement"),
        ("try:\n    pass\nexcept* ValueError:\n    pass", "except-star"),
        ("async def f():\n    await g()", "async-await"),
        ("def f():\n    yield from g()", "yield-from"),
        ("{**a, 'b': 1}", "dict-unpacking"),
        ("[*a, 1]", "iterable-unpacking-literal"),
        ("x: int = 1", "variable-annotation"),
        ("{1, 2}", "set-literal"),
        ("{k: v for k, v in items}", "dict-comprehension"),
        ("(x for x in y)", "generator-expression"),
        ("a if b else c", "conditional-expression"),
        ("with open(f) as g:\n    pass", "with-statement"),
        ("a @ b", "matrix-multiplication"),
    ],
)
def test_syntax_features(source, expected):
    assert expected in features(source)


def test_decorators_distinguish_functions_from_classes():
    assert features("@d\ndef f():\n    pass") >= {"decorator"}
    assert "class-decorator" not in features("@d\ndef f():\n    pass")
    assert "class-decorator" in features("@d\nclass C:\n    pass")


def test_starred_assignment_is_not_literal_unpacking():
    """`a, *b = c` predates PEP 448 and should not be confused with it."""
    assert "iterable-unpacking-literal" not in features("a, *b = c")


def test_builtins_are_detected():
    assert features("sum(x)") == {"sum"}
    assert features("sorted(x)") == {"sorted"}


def test_shadowed_builtins_are_ignored():
    """A locally defined `sum` is not the builtin that arrived in 2.3."""
    assert features("def sum(x):\n    return x\nsum([1])") == set()
    assert features("sum = 1\nprint(sum)") == {"print-function"}


def test_modules_are_detected():
    assert features("import tomllib") == {"tomllib"}
    assert features("from pathlib import Path") == {"pathlib"}
    assert features("import importlib.resources") == {"importlib-resources"}
    assert features("from importlib import resources") == {"importlib-resources"}


def test_attributes_are_detected():
    assert "math-isclose" in features("import math\nmath.isclose(a, b)")
    assert "itertools-batched" in features("import itertools\nitertools.batched(x, 2)")


def test_aliased_imports_are_followed():
    assert "math-isclose" in features("import math as m\nm.isclose(a, b)")


def test_from_import_use_is_detected():
    assert "functools-cache" in features(
        "from functools import cache\n@cache\ndef f():\n    pass"
    )


def test_minimum_version_takes_the_newest_feature():
    source = "import tomllib\nx = sum([1])\nif (n := 2):\n    pass"
    assert minimum_version(source) == Version(3, 11)


def test_versions_compare_numerically_not_lexically():
    assert minimum_version("import zoneinfo") == Version(3, 9)
    assert Version(3, 9) < Version(3, 10)


def test_repeated_uses_are_all_reported():
    detections = detect("sum(a)\nsum(b)")
    assert [found.lineno for found in detections] == [1, 2]


def test_detections_are_ordered_by_position():
    source = "import tomllib\nx = f'{y}'\n"
    assert [found.lineno for found in detect(source)] == [1, 2]


def test_positionless_nodes_borrow_an_enclosing_line():
    """`ast.arguments` has no line number of its own."""
    (found,) = [
        f
        for f in detect("\n\ndef f(*, a):\n    pass")
        if f.feature.id == "keyword-only-arguments"
    ]
    assert found.lineno == 3


def test_syntax_errors_propagate():
    with pytest.raises(SyntaxError):
        detect("def (")


def test_global_and_nonlocal_names_shadow_builtins():
    source = "def f():\n    global sum\n    return sum\n"
    assert "sum" not in features(source)


def test_caught_exception_names_shadow_builtins():
    source = "try:\n    pass\nexcept ValueError as sum:\n    print(sum)\n"
    assert "sum" not in features(source)


def test_relative_imports_are_skipped():
    """A relative import is local code, not a stdlib module."""
    assert features("from . import tomllib") == set()
    assert features("from .statistics import fmean") == set()


def test_attribute_on_a_non_name_is_ignored():
    """`f().isclose` has no resolvable dotted path."""
    assert features("f().isclose(a, b)") == set()
    assert features("'x'.isclose(a)") == set()
