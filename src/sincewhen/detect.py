"""Detect dated features in Python source code."""

import ast
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from typing import Any

from .features import Feature, load_features
from .versions import Version


@dataclass(frozen=True)
class Detection:
    """One use of one feature, at one place in the source."""

    feature: Feature
    lineno: int
    col_offset: int

    @property
    def added(self) -> Version:
        return self.feature.added


# Containers that PEP 585 made subscriptable in 3.9. Subscripting any
# of these names is either the new generic syntax or a variable that
# shadows the builtin, which is why the check needs to know what the
# module binds.
PEP_585_GENERICS = frozenset(
    {"list", "dict", "set", "frozenset", "tuple", "type"},
)

# Literal syntax that pins its own type. A display says what it builds,
# so `[]` is a list and `{}` is a dict no matter what surrounds it, and
# an f-string is a `str` however it is spelled.
LITERAL_TYPES: dict[type[ast.AST], str] = {
    ast.List: "list",
    ast.ListComp: "list",
    ast.Dict: "dict",
    ast.DictComp: "dict",
    ast.Set: "set",
    ast.SetComp: "set",
    ast.Tuple: "tuple",
    ast.JoinedStr: "str",
}

# The same for a constant, whose type is the type of its value. A `bool`
# answers as an `int`, because it defines no methods of its own: every
# method `True.bit_count()` can reach is `int.bit_count`.
CONSTANT_TYPES: dict[type, str] = {
    str: "str",
    bytes: "bytes",
    bool: "int",
    int: "int",
    float: "float",
    complex: "complex",
}


def _has_none_key(node: ast.Dict, _bound: frozenset[str]) -> bool:
    """A `None` key means dict unpacking, as in `{**a}`."""
    return any(key is None for key in node.keys)


def _has_starred_element(
    node: ast.List | ast.Tuple | ast.Set, _bound: frozenset[str]
) -> bool:
    """Unpacking into a literal, as in `[*a]`.

    Store context is excluded because `a, *b = c` is a different
    feature that arrived in Python 3.0.
    """
    if not isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
        return False
    return any(isinstance(element, ast.Starred) for element in node.elts)


def _has_starred_target(node: ast.List | ast.Tuple, _bound: frozenset[str]) -> bool:
    """Extended unpacking, as in `a, *rest = values`."""
    if isinstance(node.ctx, ast.Load):
        return False
    return any(isinstance(element, ast.Starred) for element in node.elts)


def _has_async_comprehension(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    _bound: frozenset[str],
) -> bool:
    return any(generator.is_async for generator in node.generators)


def _has_multiple_unpackings(node: ast.Call, _bound: frozenset[str]) -> bool:
    """More than one unpacking in a call, as in `f(*a, *b)`.

    A single `f(*a)` has always been legal, so only the second one
    dates the call to 3.5.
    """
    starred = sum(isinstance(argument, ast.Starred) for argument in node.args)
    doubled = sum(keyword.arg is None for keyword in node.keywords)
    return starred > 1 or doubled > 1


def _has_equality(node: ast.Compare, _bound: frozenset[str]) -> bool:
    """`a == b`, which is younger than Python rather than as old as it.

    0.9.1 spelled equality `=`, and could without ambiguity, because
    assignment is a statement there and never an expression. 1.0 added
    `==`, dropped `=` as a comparison, and made `>=`, `<=` and `<>` into
    single tokens rather than two adjacent ones.

    Only one operator of a chain has to be this one: `0 <= x == y` uses
    both `<=` and `==`, and each is its own claim about the version.
    """
    return any(isinstance(operator, ast.Eq) for operator in node.ops)


def _has_containment(node: ast.Compare, _bound: frozenset[str]) -> bool:
    """`x in y` or `x not in y`, both in the 0.9.1 grammar.

    The operator is all this can see, and the operator is the only part
    of containment that is as old as Python. What a release will accept
    on the right of it moved twice, and neither move is visible in an
    AST: `key in some_dict` is a `TypeError` until 2.2, where `has_key`
    was the spelling, and `'ab' in 'abc'` is one until 2.3, which is when
    a string's `in` stopped requiring a single character on the left. So
    this reports the operator and says nothing about its operands, which
    is the honest limit of a syntactic tool.
    """
    return any(isinstance(operator, ast.In | ast.NotIn) for operator in node.ops)


def _has_tuple_target(node: ast.Tuple | ast.List, _bound: frozenset[str]) -> bool:
    """A comma-separated assignment target, as in `a, b = 1, 2`.

    Store context is what makes this unpacking rather than a display:
    `except (A, B)` and `x = (1, 2)` are both loads. Everything that
    stores into a tuple is unpacking of some kind, including `for a, b in
    pairs`, `with open(p) as (a, b)`, the `a, b = b, a` swap, and a
    nested `a, (b, c) = 1, (2, 3)`, all of which run under 0.9.1.

    A starred target is deliberately not excluded. `a, *rest = values` is
    tuple unpacking too, and reporting both it and the 3.0 feature is two
    true statements rather than a double count: the newer one sets the
    floor.
    """
    return isinstance(node.ctx, ast.Store)


def _has_inequality(node: ast.Compare, _bound: frozenset[str]) -> bool:
    """`a != b`, which arrived in 1.0 alongside `<>`.

    Only `!=` is detectable, and not because it is the survivor: `<>`
    lasted until 3.0 removed it, so a 3.14 parser cannot produce a node
    for it at all. Reporting `!=` says nothing either way about `<>`,
    which is a question for a `removed_in` field rather than this one.
    """
    return any(isinstance(operator, ast.NotEq) for operator in node.ops)


def _is_async_generator(node: ast.AsyncFunctionDef, _bound: frozenset[str]) -> bool:
    """An `async def` that yields, which needed 3.6.

    Nested functions are skipped, since a plain generator defined inside
    a coroutine is not itself an async generator.
    """
    return any(
        isinstance(inner, ast.Yield)
        for inner in _own_body(node)
        if not isinstance(inner, ast.Lambda)
    )


def _own_body(node: ast.AST):
    """Every node inside `node` that is not inside a nested function."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        yield child
        yield from _own_body(child)


def _is_builtin_generic(node: ast.Subscript, bound: frozenset[str]) -> bool:
    """Subscripting a builtin container, as in `list[int]` (PEP 585)."""
    return (
        isinstance(node.value, ast.Name)
        and node.value.id in PEP_585_GENERICS
        and node.value.id not in bound
    )


def _is_zero_argument_super(node: ast.Call, bound: frozenset[str]) -> bool:
    """`super()` with no arguments, which needs the 3.0 compiler help."""
    return (
        isinstance(node.func, ast.Name)
        and node.func.id == "super"
        and "super" not in bound
        and not node.args
        and not node.keywords
    )


def _has_complex_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, _bound: frozenset[str]
) -> bool:
    """A decorator that the pre-3.9 grammar would have rejected.

    Until PEP 614 a decorator had to be a dotted name, optionally
    called. Anything else -- a subscript, a comparison, a lambda -- is
    3.9 or newer.
    """
    return any(
        not _is_dotted_name(
            decorator.func if isinstance(decorator, ast.Call) else decorator
        )
        for decorator in node.decorator_list
    )


def _is_dotted_name(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _has_except_and_finally(node: ast.Try, _bound: frozenset[str]) -> bool:
    """One statement with both `except` and `finally`, unified in 2.5."""
    return bool(node.handlers and node.finalbody)


def _has_several_context_managers(
    node: ast.With | ast.AsyncWith, _bound: frozenset[str]
) -> bool:
    """`with a, b:` rather than two nested `with` statements."""
    return len(node.items) > 1


def _has_metaclass_keyword(node: ast.ClassDef, _bound: frozenset[str]) -> bool:
    """`class C(metaclass=M)`, which replaced `__metaclass__` in 3.0."""
    return any(keyword.arg == "metaclass" for keyword in node.keywords)


def _has_named_handler(node: ast.ExceptHandler, _bound: frozenset[str]) -> bool:
    """`except E as name`, the spelling that replaced `except E, name`."""
    return node.name is not None


def _has_cause(node: ast.Raise, _bound: frozenset[str]) -> bool:
    """`raise X from Y`, which is exception chaining."""
    return node.cause is not None


def _is_bytes(node: ast.Constant, _bound: frozenset[str]) -> bool:
    """A `b"..."` literal."""
    return isinstance(node.value, bytes)


def _has_starred_subscript(node: ast.Subscript, _bound: frozenset[str]) -> bool:
    """Unpacking inside a subscript, as in `tuple[*Ts]` (PEP 646).

    A starred subscript is always parsed into a tuple, even when it is
    the only thing in the brackets, so there is no bare `Starred` slice
    to look for.
    """
    return isinstance(node.slice, ast.Tuple) and any(
        isinstance(element, ast.Starred) for element in node.slice.elts
    )


# Checks are dispatched by name from the dataset, so the node type is
# only known at runtime. Each predicate still annotates the node types
# it actually accepts; `Any` here is the dynamic-dispatch boundary.
# Every check also receives the names the module binds, so that a
# feature keyed on a builtin can tell a real use from a shadowed one.
CHECKS: dict[str, Callable[[Any, frozenset[str]], bool]] = {
    "has_none_key": _has_none_key,
    "has_starred_element": _has_starred_element,
    "has_starred_target": _has_starred_target,
    "has_async_comprehension": _has_async_comprehension,
    "has_multiple_unpackings": _has_multiple_unpackings,
    "has_equality": _has_equality,
    "has_inequality": _has_inequality,
    "has_containment": _has_containment,
    "has_tuple_target": _has_tuple_target,
    "is_async_generator": _is_async_generator,
    "is_builtin_generic": _is_builtin_generic,
    "is_zero_argument_super": _is_zero_argument_super,
    "has_complex_decorator": _has_complex_decorator,
    "has_except_and_finally": _has_except_and_finally,
    "has_several_context_managers": _has_several_context_managers,
    "has_metaclass_keyword": _has_metaclass_keyword,
    "has_named_handler": _has_named_handler,
    "has_cause": _has_cause,
    "is_bytes": _is_bytes,
    "has_starred_subscript": _has_starred_subscript,
}


class _Index:
    """Feature lookups keyed by what they match on."""

    def __init__(self, features: Iterable[Feature]):
        self.by_node: dict[str, list[Feature]] = {}
        self.by_builtin: dict[str, Feature] = {}
        self.by_module: dict[str, Feature] = {}
        self.by_attribute: dict[str, Feature] = {}
        self.by_method: dict[str, Feature] = {}
        for feature in features:
            for name in feature.nodes:
                self.by_node.setdefault(name, []).append(feature)
            for name in feature.builtins:
                self.by_builtin[name] = feature
            for name in feature.modules:
                self.by_module[name] = feature
            for name in feature.attributes:
                self.by_attribute[name] = feature
            for name in feature.methods:
                self.by_method[name] = feature
        # The types those methods hang off, taken from the dataset rather
        # than listed again here, so the two cannot drift apart.
        self.method_types = frozenset(name.partition(".")[0] for name in self.by_method)


@cache
def _index() -> _Index:
    return _Index(load_features())


def _bound_names(tree: ast.AST) -> frozenset[str]:
    """Names the module binds itself.

    A module that defines its own `sum` is not using the builtin, so
    shadowed names are skipped entirely rather than reported wrongly.
    """
    names = set()
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                names.add(name)
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                names.add(name)
            case ast.arg(arg=name):
                names.add(name)
            case ast.alias(name=name, asname=asname):
                names.add(asname or name.partition(".")[0])
            case ast.Global(names=found) | ast.Nonlocal(names=found):
                names.update(found)
            case ast.ExceptHandler(name=str() as name):
                names.add(name)
    return frozenset(names)


class _Detector(ast.NodeVisitor):
    def __init__(self, index: _Index, bound_names: frozenset[str]):
        self.index = index
        self.bound_names = bound_names
        self.detections: list[Detection] = []
        self.aliases: dict[str, str] = {}
        self._position = (1, 0)

    def visit(self, node: ast.AST) -> None:
        # Some matched nodes (`arguments`) carry no position of their
        # own, so the nearest enclosing position is tracked instead.
        lineno = getattr(node, "lineno", None)
        previous = self._position
        if lineno is not None:
            self._position = (lineno, getattr(node, "col_offset", 0))
        self._match_node(node)
        handler = getattr(self, f"visit_{type(node).__name__}", None)
        if handler is None:
            self.generic_visit(node)
        else:
            handler(node)
        self._position = previous

    def _match_node(self, node: ast.AST) -> None:
        for feature in self.index.by_node.get(type(node).__name__, ()):
            if feature.requires and not getattr(node, feature.requires, None):
                continue
            if feature.check and not CHECKS[feature.check](node, self.bound_names):
                continue
            self._record(feature)

    def _record(self, feature: Feature) -> None:
        lineno, col_offset = self._position
        self.detections.append(Detection(feature, lineno, col_offset))

    def _record_module(self, dotted: str) -> None:
        """Report the most specific module the dataset knows about.

        `import importlib.resources` needs both `importlib` and
        `importlib.resources`, but only the submodule is worth saying:
        it is the newer of the two, so it sets the floor on its own, and
        naming the parent as well would be noise.
        """
        parts = dotted.split(".")
        for size in range(len(parts), 0, -1):
            feature = self.index.by_module.get(".".join(parts[:size]))
            if feature is not None:
                self._record(feature)
                return

    def _record_attribute(self, dotted: str) -> None:
        feature = self.index.by_attribute.get(dotted)
        if feature is not None:
            self._record(feature)

    def _record_method(self, node: ast.Attribute) -> None:
        """Report a method of a builtin type, where the type is certain.

        `x.removeprefix(...)` says nothing about `x`: it could be a
        `str`, a `pathlib.PurePath`, or a class written this morning, and
        the AST cannot tell. Two receivers do say, and only those two are
        read:

        - a literal, whose type is its own syntax
        - the type's own name, as in `dict.fromkeys(keys)`, unless the
          module has bound that name to something else

        Everything else is left alone, because a wrong version number is
        worse than a missing one. Those entries stay searchable, which is
        the question this dataset mostly answers.
        """
        receiver = self._receiver_type(node.value)
        if receiver is None:
            return
        feature = self.index.by_method.get(f"{receiver}.{node.attr}")
        if feature is not None:
            self._record(feature)

    def _receiver_type(self, node: ast.expr) -> str | None:
        """The builtin type `node` certainly is, if there is one."""
        match node:
            case ast.Constant(value=value):
                return CONSTANT_TYPES.get(type(value))
            case ast.Name(id=name):
                if name in self.index.method_types and name not in self.bound_names:
                    return name
                return None
            case _:
                return LITERAL_TYPES.get(type(node))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            if node.id not in self.bound_names:
                feature = self.index.by_builtin.get(node.id)
                if feature is not None:
                    self._record(feature)
            elif node.id in self.aliases:
                self._record_attribute(self.aliases[node.id])
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = self._dotted_name(node)
        if dotted is not None:
            self._record_attribute(dotted)
        self._record_method(node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_module(alias.name)
            bound = alias.asname or alias.name.partition(".")[0]
            self.aliases[bound] = alias.name if alias.asname else bound
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                # `_record_module` walks back up the dotted path, so
                # this covers the package too: `from pathlib import
                # Path` reports `pathlib`, and `from importlib import
                # resources` reports the submodule instead.
                self._record_module(dotted)
                self._record_attribute(dotted)
                self.aliases[alias.asname or alias.name] = dotted
        self.generic_visit(node)

    def _dotted_name(self, node: ast.Attribute) -> str | None:
        """Resolve `m.isclose` to `math.isclose`, following aliases."""
        parts = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(self.aliases.get(current.id, current.id))
        return ".".join(reversed(parts))


def detect(source: str | ast.AST, *, filename: str = "<string>") -> list[Detection]:
    """Find every dated feature used in `source`, in source order.

    A feature used several times is reported once per use.
    """
    tree = source if isinstance(source, ast.AST) else ast.parse(source, filename)
    detector = _Detector(_index(), _bound_names(tree))
    detector.visit(tree)
    return sorted(
        detector.detections,
        key=lambda found: (found.lineno, found.col_offset, found.feature.id),
    )


def minimum_version(source: str | ast.AST) -> Version | None:
    """The oldest Python that can run `source`, as far as we can tell.

    Returns `None` when nothing in the dataset was detected, which
    means no known feature sets a floor rather than that the code runs
    anywhere.
    """
    detections = detect(source)
    if not detections:
        return None
    return max(found.added for found in detections)
