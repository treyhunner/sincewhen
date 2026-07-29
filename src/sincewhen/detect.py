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


def _has_none_key(node: ast.Dict) -> bool:
    """A `None` key means dict unpacking, as in `{**a}`."""
    return any(key is None for key in node.keys)


def _has_starred_element(node: ast.List | ast.Tuple | ast.Set) -> bool:
    """Unpacking into a literal, as in `[*a]`.

    Store context is excluded because `a, *b = c` is a different
    feature that arrived in Python 3.0.
    """
    if not isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
        return False
    return any(isinstance(element, ast.Starred) for element in node.elts)


def _has_async_comprehension(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> bool:
    return any(generator.is_async for generator in node.generators)


# Checks are dispatched by name from the dataset, so the node type is
# only known at runtime. Each predicate still annotates the node types
# it actually accepts; `Any` here is the dynamic-dispatch boundary.
CHECKS: dict[str, Callable[[Any], bool]] = {
    "has_none_key": _has_none_key,
    "has_starred_element": _has_starred_element,
    "has_async_comprehension": _has_async_comprehension,
}


class _Index:
    """Feature lookups keyed by what they match on."""

    def __init__(self, features: Iterable[Feature]):
        self.by_node: dict[str, list[Feature]] = {}
        self.by_builtin: dict[str, Feature] = {}
        self.by_module: dict[str, Feature] = {}
        self.by_attribute: dict[str, Feature] = {}
        for feature in features:
            for name in feature.nodes:
                self.by_node.setdefault(name, []).append(feature)
            for name in feature.builtins:
                self.by_builtin[name] = feature
            for name in feature.modules:
                self.by_module[name] = feature
            for name in feature.attributes:
                self.by_attribute[name] = feature


@cache
def _index() -> _Index:
    return _Index(load_features())


def _bound_names(tree: ast.AST) -> set[str]:
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
    return names


class _Detector(ast.NodeVisitor):
    def __init__(self, index: _Index, bound_names: set[str]):
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
            if feature.check and not CHECKS[feature.check](node):
                continue
            self._record(feature)

    def _record(self, feature: Feature) -> None:
        lineno, col_offset = self._position
        self.detections.append(Detection(feature, lineno, col_offset))

    def _record_module(self, dotted: str) -> None:
        parts = dotted.split(".")
        for size in range(len(parts), 0, -1):
            feature = self.index.by_module.get(".".join(parts[:size]))
            if feature is not None:
                self._record(feature)

    def _record_attribute(self, dotted: str) -> None:
        feature = self.index.by_attribute.get(dotted)
        if feature is not None:
            self._record(feature)

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
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_module(alias.name)
            bound = alias.asname or alias.name.partition(".")[0]
            self.aliases[bound] = alias.name if alias.asname else bound
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self._record_module(node.module)
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
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
