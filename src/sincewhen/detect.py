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

# What a method's receiver is called inside the class that defines it.
# A convention rather than a rule, which is why it is only read where
# the enclosing class says what it is: see `_inherited_owner`.
SELF = "self"

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


def _has_dict_items(node: ast.Dict, _bound: frozenset[str]) -> bool:
    """`{'k': 1}`, a dict display with something between the braces.

    The empty display is as old as Python and the pairs are not: 0.9.1
    spells a dict `'{' '}'` in its `atom` rule and has no `dictmaker`
    rule at all, so `{}` is 0.9 and `{'k': 1}` is 1.0.

    A key of `None` is `{**a}` rather than a pair, so at least one real
    key is required and a display of nothing but unpackings is the 3.5
    feature alone.
    """
    return any(key is not None for key in node.keys)


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


def _has_call_unpacking(node: ast.Call, _bound: frozenset[str]) -> bool:
    """`f(*args)` or `f(**kwargs)`, unpacking at a call site.

    Both spellings arrived in the same 1.6 grammar line, so they are one
    feature rather than two; `apply(f, args)` was how it was written
    before. `f(*a, *b)` reports this and the 3.5 `multiple-unpackings`
    entry both, which is two true statements about one call.

    Collecting is the older half of the pair and a different node:
    `def f(*args)` is 1.0 and `def f(**kwargs)` is 1.5, and neither is a
    `Call`.
    """
    return any(isinstance(argument, ast.Starred) for argument in node.args) or any(
        keyword.arg is None for keyword in node.keywords
    )


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
    "has_dict_items": _has_dict_items,
    "has_starred_element": _has_starred_element,
    "has_starred_target": _has_starred_target,
    "has_async_comprehension": _has_async_comprehension,
    "has_multiple_unpackings": _has_multiple_unpackings,
    "has_call_unpacking": _has_call_unpacking,
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
        #
        # `rpartition`, because an owner is a builtin type or a class in
        # a module and the second is spelled dotted: `str.removeprefix`
        # hangs off `str` and `unittest.TestCase.assertNotEndsWith` off
        # `unittest.TestCase`. Reading the head instead would call the
        # owner `unittest`, which is a module and answers a different
        # question.
        self.method_owners = frozenset(
            name.rpartition(".")[0] for name in self.by_method
        )


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
        # The bases of each class currently being walked into, resolved
        # to dotted names. Only the innermost is ever read.
        self._bases: list[tuple[str, ...]] = []
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
        """Report a method of a known type, where the type is certain.

        `x.removeprefix(...)` says nothing about `x`: it could be a
        `str`, a `pathlib.PurePath`, or a class written this morning, and
        the AST cannot tell. Four receivers do say, and only those four
        are read:

        - a literal, whose type is its own syntax
        - the type's own name, as in `dict.fromkeys(keys)`, unless the
          module has bound that name to something else
        - a class the module imported, by either spelling:
          `unittest.TestCase.assertNotEndsWith` or a bare `TestCase`
          that `from unittest import TestCase` bound
        - `self`, inside a class that says in its own bases which type
          it is: see `_inherited_owner`

        Everything else is left alone, because a wrong version number is
        worse than a missing one. Those entries stay searchable, which is
        the question this dataset mostly answers.
        """
        if not isinstance(node.ctx, ast.Load):
            # `self.assertHasAttr = 3` binds the name rather than
            # calling it, and reporting a 3.14 floor for a line that
            # defines its own replacement is exactly backwards. This
            # could not arise while every owner was a builtin type,
            # since `"".removeprefix = f` is not something to write.
            #
            # An `attributes` match is deliberately left alone: setting
            # `sys.ps1` really is a use of a documented attribute, which
            # is not true of overwriting a method.
            return
        owner = (
            self._inherited_owner(node.attr)
            if isinstance(node.value, ast.Name) and node.value.id == SELF
            else self._receiver_type(node.value)
        )
        if owner is None:
            return
        feature = self.index.by_method.get(f"{owner}.{node.attr}")
        if feature is not None:
            self._record(feature)

    def _inherited_owner(self, attr: str) -> str | None:
        """The type `self.<attr>` reaches, where the bases settle it.

        `self.assertNotEndsWith(...)` is a method call on a receiver
        whose type the AST does not carry, and one whose type the
        enclosing `class Test(unittest.TestCase):` line does. That line
        is the same kind of certainty a literal gives: the module said
        which type this is, in its own source, three lines up.

        Only the innermost class, and only its own bases. A subclass of
        a subclass says nothing here, since resolving that would mean
        following a name into another module, and `class
        Test(TestCase):` where `TestCase` came `from django.test`
        resolves to `django.test.TestCase` and matches nothing, which is
        the right answer rather than a near miss.

        A class that defines the method itself is not calling this one.
        `bound_names` is what says so, exactly as it does for a module
        that binds its own `sum`, and it is deliberately the module's
        names rather than the class's. That is coarse in both
        directions and coarse the safe way: one class's
        `assertNotEndsWith` helper silences the name for every class in
        the file, and a helper on a mixin in the same file silences it
        for the classes that inherit the mixin, which no class-scoped
        reading could see at all.
        """
        if attr in self.bound_names:
            return None
        for owner in self._bases[-1] if self._bases else ():
            if f"{owner}.{attr}" in self.index.by_method:
                return owner
        return None

    def _receiver_type(self, node: ast.expr) -> str | None:
        """The type `node` certainly is, if there is one.

        A builtin type answers by its bare name and a class in a module
        by its dotted one, which is why an imported name is resolved
        through `aliases` first: `TestCase` is bound by the import that
        names it, so the shadowing check that protects `dict` would
        reject the very binding that makes this one certain.
        """
        match node:
            case ast.Constant(value=value):
                return CONSTANT_TYPES.get(type(value))
            case ast.Name(id=name):
                imported = self.aliases.get(name)
                if imported in self.index.method_owners:
                    return imported
                if name in self.index.method_owners and name not in self.bound_names:
                    return name
                return None
            case ast.Attribute():
                dotted = self._dotted_name(node)
                return dotted if dotted in self.index.method_owners else None
            case _:
                return LITERAL_TYPES.get(type(node))

    def visit_Constant(self, node: ast.Constant) -> None:
        """`True`, `False` and `None` are builtin names, folded into constants.

        The parser never produces a `Name` for one, because all three are
        keywords, so `visit_Name` cannot see them and a `builtins` entry
        for `True` would match nothing at all. They are ordinary members
        of the builtins namespace otherwise: `getattr(builtins, "True")`
        finds one, and `True` was a name before 3.0 made it a keyword.

        Compared by identity rather than looked up in a dict, because
        `True == 1` and `hash(True) == hash(1)`, so any mapping keyed on
        the value reports `True` for the literal `1`.

        Shadowing needs no check here, unlike every other builtin: all
        three are keywords, so `True = 0` is a syntax error and nothing
        can rebind them.
        """
        for value, name in ((True, "True"), (False, "False"), (None, "None")):
            if node.value is value:
                feature = self.index.by_builtin.get(name)
                if feature is not None:
                    self._record(feature)
                break
        self.generic_visit(node)

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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Remember what this class says it is, while walking its body.

        Resolved on the way in rather than looked up later, because the
        aliases a base name depends on are bound by imports the walk has
        already passed, and because a nested class has to shadow the one
        around it and hand it back on the way out.
        """
        self._bases.append(
            tuple(
                owner
                for base in node.bases
                if (owner := self._base_owner(base)) is not None
            )
        )
        self.generic_visit(node)
        self._bases.pop()

    def _base_owner(self, node: ast.expr) -> str | None:
        """A base class as a dotted name, following aliases.

        Read the same way `_receiver_type` reads a `Name`, and it has to
        be: a module that writes its own `class dict:` and then
        `class Foo(dict):` is not subclassing the builtin, so `self`
        inside `Foo` is not a `dict`. Rejecting the shadowed name for
        `dict.fromkeys(...)` and accepting it here would be the two
        paths disagreeing about one binding.
        """
        match node:
            case ast.Name(id=name):
                imported = self.aliases.get(name)
                if imported is not None:
                    return imported
                return None if name in self.bound_names else name
            case ast.Attribute():
                return self._dotted_name(node)
            case _:
                return None

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

    Returns `None` when nothing detected sets a floor, which means no
    known feature requires a particular release rather than that the
    code runs anywhere.

    A bounded feature ("1.5 or earlier") sets no floor: its version is
    a limit on what the sources could read, not a date, so treating it
    as one could claim a minimum newer than the truth.
    """
    floors = [found.added for found in detect(source) if not found.feature.or_earlier]
    if not floors:
        return None
    return max(floors)
