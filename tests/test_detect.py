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
        ("def f():\n    yield 1", "generator-function"),
        (
            "try:\n    pass\nexcept E:\n    pass\nfinally:\n    pass",
            "unified-try-except-finally",
        ),
        ("from . import thing", "relative-import"),
        ("try:\n    pass\nexcept E as error:\n    pass", "except-as"),
        ("x = b'bytes'", "bytes-literal"),
        ("a, *rest = values", "starred-assignment"),
        ("[first, *rest] = values", "starred-assignment"),
        ("class C(metaclass=Meta):\n    pass", "metaclass-keyword"),
        ("raise ValueError from error", "raise-from"),
        ("class C:\n    def f(self):\n        super().f()", "zero-argument-super"),
        ("with open(a) as f, open(b) as g:\n    pass", "several-context-managers"),
        ("f(*a, *b)", "multiple-unpackings"),
        ("f(**a, **b)", "multiple-unpackings"),
        ("async def f():\n    yield 1", "async-generator"),
        ("x: list[int] = []", "builtin-generic"),
        ("@registry[name]\ndef f():\n    pass", "relaxed-decorator"),
        ("x: tuple[*Ts]", "starred-subscript"),
        ("from __future__ import annotations", "future-annotations"),
        ("a == b", "equality-operator"),
        ("a != b", "inequality-operator"),
        # One operator of a chain is enough, and each is its own claim.
        ("0 <= x == y", "equality-operator"),
        ("a <= b != c", "inequality-operator"),
    ],
)
def test_syntax_features(source, expected):
    assert expected in features(source)


@pytest.mark.parametrize(
    "source, unwanted",
    [
        # A single unpacking in a call has always been legal.
        ("f(*a)", "multiple-unpackings"),
        ("f(**a)", "multiple-unpackings"),
        ("f(*a, **b)", "multiple-unpackings"),
        # `super(C, self)` is the spelling that works everywhere.
        (
            "class C:\n    def f(self):\n        super(C, self).f()",
            "zero-argument-super",
        ),
        # Subscripting a local list is not PEP 585.
        ("list = [1, 2]\nlist[0]", "builtin-generic"),
        # An ordinary subscript, and an ordinary decorator.
        ("x = values[0]", "starred-subscript"),
        ("@decorators.cache\ndef f():\n    pass", "relaxed-decorator"),
        ("@cache()\ndef f():\n    pass", "relaxed-decorator"),
        # A coroutine that only awaits is not an async generator, and
        # neither is one that merely contains a nested generator.
        ("async def f():\n    await g()", "async-generator"),
        ("async def f():\n    def inner():\n        yield 1", "async-generator"),
        # `except E:` with no name predates the `as` spelling.
        ("try:\n    pass\nexcept E:\n    pass", "except-as"),
        # One context manager is the 2.5 `with`, not the 3.1 form.
        ("with open(a) as f:\n    pass", "several-context-managers"),
        # try/except and try/finally were separate statements until 2.5.
        ("try:\n    pass\nfinally:\n    pass", "unified-try-except-finally"),
        ("try:\n    pass\nexcept E:\n    pass", "unified-try-except-finally"),
        # Every other comparison is as old as Python: `<`, `>`, `is` and
        # `in` are all in the 0.9.1 grammar, and only `==` and `!=` are
        # the 1.0 additions.
        ("a < b", "equality-operator"),
        ("a > b", "inequality-operator"),
        ("a is b", "equality-operator"),
        ("a is not b", "inequality-operator"),
        ("x in y", "equality-operator"),
        ("x not in y", "inequality-operator"),
        ("a == b", "inequality-operator"),
        ("a != b", "equality-operator"),
        # An assignment is not a comparison, which is the whole reason
        # 0.9.1 could spell equality `=`.
        ("a = b", "equality-operator"),
    ],
)
def test_narrow_syntax_matchers_do_not_over_fire(source, unwanted):
    assert unwanted not in features(source)


def test_generator_function_is_not_a_generator_expression():
    """`yield` in a nested function still makes that function one."""
    assert "generator-function" in features("def f():\n    def g():\n        yield 1")
    assert "generator-function" not in features("x = (i for i in y)")


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
    """A member import reports the member and the module it came from.

    Both are real: the import needs the module to exist and the name in
    it to exist. Deciding which of the two is worth printing is the
    reporter's job, not the detector's.
    """
    assert features("import tomllib") == {"tomllib"}
    assert features("from pathlib import Path") == {"pathlib", "pathlib-path"}
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
    """A relative import is local code, not a stdlib module.

    The `from . import x` syntax is itself dated, so the relative-import
    feature is expected; what must not appear is a stdlib module named
    after whatever the local package happens to call its submodules.
    """
    assert features("from . import tomllib") == {"relative-import"}
    assert features("from .statistics import fmean") == {"relative-import"}


def test_attribute_on_a_non_name_is_ignored():
    """`f().isclose` has no resolvable dotted path."""
    assert features("f().isclose(a, b)") == set()
    assert features("'x'.isclose(a)") == set()


@pytest.mark.parametrize(
    "source, expected",
    [
        ('"Mr. Smith".removeprefix("Mr. ")', "str-removeprefix"),
        ('f"{name}".removesuffix("!")', "str-removesuffix"),
        ('b"abc".hex()', "bytes-hex"),
        ("[].copy()", "list-copy-clear"),
        ("[x for x in y].clear()", "list-copy-clear"),
        ("(255).bit_count()", "int-bit-count"),
        ("(2.0).is_integer()", "float-is-integer"),
        ("True.bit_count()", "int-bit-count"),
        # The ancient methods, which only the type's own method table
        # dates: no doc build says when any of these arrived.
        ('"abc".split()', "str-split"),
        ('"abc".startswith("a")', "str-startswith"),
        ("[].append(x)", "list-append"),
        ("[].extend(x)", "list-extend"),
        ("{}.setdefault(k, v)", "dict-setdefault"),
        ("{}.keys()", "dict-keys"),
        ("{1, 2}.add(3)", "set-add"),
        # The type's own name is as certain as a literal is.
        ('dict.fromkeys("abc")', "dict-fromkeys"),
        ('str.casefold("HI")', "str-casefold"),
        ("type.mro(int)", "type-mro"),
    ],
)
def test_methods_are_detected_where_the_receiver_pins_the_type(source, expected):
    assert expected in features(source)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("[].copy()", "list-copy-clear"),
        ("{}.copy()", "dict-copy"),
        ("{1, 2}.copy()", "set-copy"),
        ('"a".index("a")', "str-index"),
        ("[].index(x)", "list-index"),
    ],
)
def test_one_method_name_is_a_different_age_on_each_type(source, expected):
    """A dict is not a list, and a set is not a dict.

    `copy()` is 1.5 on a dict, 2.4 on a set and 3.3 on a list, so a
    receiver whose type is certain has to pick exactly one of them.
    """
    assert {found.feature.id for found in detect(source) if found.feature.methods} == {
        expected
    }


@pytest.mark.parametrize(
    "source",
    [
        # Anything at all can define these, so a bare name proves nothing.
        'value.removeprefix("x")',
        "self.rows.copy()",
        "get_row().copy()",
        "rows[0].clear()",
        # A shadowed type name is not the type.
        'dict = {"a": 1}\ndict.fromkeys("abc")',
    ],
)
def test_methods_are_not_detected_on_an_uncertain_receiver(source):
    assert not {found.feature.id for found in detect(source) if found.feature.methods}


def test_a_method_and_its_type_are_both_reported():
    """Two true statements about one expression, at two ages.

    `dict.fromkeys(keys)` needs the `dict` type, which arrived in 2.2,
    and the method, which arrived in 2.3. The newer one sets the floor
    and the older one is still worth saying.
    """
    assert features('dict.fromkeys("abc")') == {"dict", "dict-fromkeys"}
    assert minimum_version('dict.fromkeys("abc")') == Version(2, 3)
