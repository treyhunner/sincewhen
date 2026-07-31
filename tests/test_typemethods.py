"""The decisions `typemethods.py` makes about a type's method table.

Reading the 500 MB corpus is not exercised here. What is exercised is
everything between a C file and a version claim, because that is where a
mistake becomes a wrong version number rather than a crash:

- **finding the table**, which moves from a `tp_getattr` function calling
  `findmethod()` to a `tp_methods` slot in 2.2, and which has to be the
  table the type names rather than whichever `{"name", func}` sits
  nearest.
- **reading it strictly and its absence generously**, so that a row
  inside an `#if 0` neither dates a method nor rules it out. `str.zfill`
  is exactly that, in two separate releases.
- **the family rule**, which decides whether `str` means the 2.x string,
  unicode, or both, and gets `str.encode` wrong in either direction if it
  picks one file per type.
"""

import pytest
import typemethods
from typemethods import TypeSource, types_in_text

# A 2.2-era type, whose methods hang off a `tp_methods` slot.
MODERN = """
static PyMethodDef list_methods[] = {
\t{"append", (PyCFunction)listappend, METH_O, append_doc},
\t{"__getitem__", (PyCFunction)list_subscript, METH_O, getitem_doc},
\t{NULL, NULL}
};

static PyMethodDef other_methods[] = {
\t{"leaked", (PyCFunction)other_leaked, METH_O, leaked_doc},
\t{NULL, NULL}
};

PyTypeObject PyList_Type = {
\tPyObject_HEAD_INIT(&PyType_Type)
\t0,
\t"list",
\tsizeof(PyListObject),
\t0,
\tPyObject_GenericGetAttr,\t\t/* tp_getattro */
\tlist_methods,\t\t\t\t/* tp_methods */
\t0,\t\t\t\t\t/* tp_members */
};
"""

# The same type as 1.5 writes it: no `tp_methods` slot at all, and the
# table reached through the function in `tp_getattr`.
ANCIENT = """
static struct methodlist list_methods[] = {
\t{"append",\tlistappend},
\t{NULL,\t\tNULL}
};

static object *
list_getattr(f, name)
\tlistobject *f;
\tchar *name;
{
\treturn findmethod(list_methods, (object *)f, name);
}

typeobject Listtype = {
\tOB_HEAD_INIT(&Typetype)
\t0,
\t"list",
\tsizeof(listobject),
\t0,
\t(destructor)list_dealloc,\t/*tp_dealloc*/
\t(getattrfunc)list_getattr,\t/*tp_getattr*/
};
"""


def test_a_modern_type_names_its_method_table():
    (found,) = types_in_text(MODERN, "Objects/listobject.c").values()
    assert found.methods == {"append"}
    assert found.file == "Objects/listobject.c"


def test_a_dunder_row_is_not_read():
    """`list.__getitem__` is a slot from 0.9.1 and a row from 2.4.

    2.4 added the row so that a list could be pickled, so the row dates
    the row. A special method is filled in by the type structure itself
    and no table can date it, which is why every dunder is left to the
    docs.
    """
    (found,) = types_in_text(MODERN, "Objects/listobject.c").values()
    assert "__getitem__" not in found.methods


def test_a_neighbouring_table_does_not_leak():
    """`{"name", func}` is ordinary C, so the table has to be the named one."""
    (found,) = types_in_text(MODERN, "Objects/listobject.c").values()
    assert "leaked" not in found.methods


def test_a_pre_2_2_type_is_read_through_its_getattr():
    (found,) = types_in_text(ANCIENT, "Objects/listobject.c").values()
    assert found.methods == {"append"}


def test_the_python_level_name_is_the_key_not_the_c_identifier():
    """`Listtype`, `PyList_Type` and `list_methods` are all spellings.

    Only `tp_name` says what the type is called in Python, and the
    C identifier changes twice across this corpus while `tp_name` does
    not.
    """
    assert set(types_in_text(ANCIENT, "x.c")) == {"list"}
    assert set(types_in_text(MODERN, "x.c")) == {"list"}


def test_a_type_this_method_does_not_speak_for_is_skipped():
    """A tp_name outside every family is not a builtin type worth dating."""
    text = MODERN.replace('"list"', '"list (immutable, during sort)"')
    assert types_in_text(text, "x.c") == {}


def test_a_conditional_row_is_neither_bound_nor_absent():
    """The `str.zfill` case, which is the whole reason for the split.

    1.6 and 2.2 both carry `{"zfill", ...}` inside an `#if 0`, because
    the method really arrived in 2.2.2. So the row cannot show the
    release had it, and the release cannot be shown to lack it either.
    """
    text = MODERN.replace(
        '\t{"append"',
        '#if 0\n\t{"zfill", (PyCFunction)string_zfill, METH_VARARGS, zfill_doc},\n'
        "#endif\n"
        '\t{"append"',
    )
    (found,) = types_in_text(text, "x.c").values()
    assert "zfill" not in found.methods
    assert "zfill" in found.literals


def test_a_getset_table_is_not_a_method_table():
    """Attributes were `strcmp` calls in `tp_getattr` before 2.2.

    So a name missing from a 2.1 member table is not a name missing from
    2.1, and reading those tables would date every attribute to the
    release that unified the type system.
    """
    text = MODERN.replace(
        "\tlist_methods,\t\t\t\t/* tp_methods */", "\t0,\t\t\t/* tp_methods */"
    ).replace("\t0,\t\t\t\t\t/* tp_members */", "\tlist_methods,\t\t/* tp_getset */")
    (found,) = types_in_text(text, "x.c").values()
    assert found.methods == frozenset()


@pytest.fixture
def corpus(monkeypatch):
    """Install a small release-by-release view of the source tree.

    Each release maps a `tp_name` to what it binds and what it so much as
    mentions, which is all the dating rules read.
    """
    releases: dict[str, dict[str, TypeSource]] = {}

    def install(version, tp_name, methods, literals=None):
        releases.setdefault(version, {})[tp_name] = TypeSource(
            file=f"Objects/{tp_name}object.c",
            methods=frozenset(methods),
            literals=frozenset(methods if literals is None else literals),
        )

    monkeypatch.setattr(
        typemethods, "types_in", lambda version: releases.get(version, {})
    )
    monkeypatch.setattr(typemethods, "readable", lambda: ("1.5", "1.6", "2.0"))
    return install


def test_a_method_in_the_oldest_release_can_only_be_bounded(corpus):
    for version in ("1.5", "1.6", "2.0"):
        corpus(version, "list", ["append"])
    assert typemethods._date_one_type("list") == {
        "list.append": {"file": "Objects/listobject.c", "floor": "1.5"}
    }


def test_a_method_the_release_before_lacks_is_dated(corpus):
    corpus("1.5", "list", [])
    corpus("1.6", "list", ["append"])
    corpus("2.0", "list", ["append"])
    assert typemethods._date_one_type("list")["list.append"] == {
        "file": "Objects/listobject.c",
        "added": "1.6",
        "absent_in": "1.5",
        "present_in": "1.6",
    }


def test_a_method_the_release_before_only_mentions_is_bounded(corpus):
    """A mention is not a binding, and it is not an absence either."""
    corpus("1.5", "list", [], literals=["append"])
    corpus("1.6", "list", ["append"])
    corpus("2.0", "list", ["append"])
    assert typemethods._date_one_type("list")["list.append"] == {
        "file": "Objects/listobject.c",
        "floor": "1.6",
    }


def test_a_type_absent_from_a_release_lacks_every_method(corpus):
    """`setobject.c` arrives in 2.4, so every `set` method is 2.4.

    2.3 has a `Set` class in `Lib/sets.py` under another name, and no
    `set` type at all, so the absence is the type's rather than the
    method's.
    """
    corpus("2.0", "set", ["add"])
    assert typemethods._date_one_type("set")["set.add"] == {
        "file": "Objects/setobject.c",
        "added": "2.0",
        "absent_in": "1.6",
        "present_in": "2.0",
    }


def test_a_family_has_to_agree_before_a_method_is_dated(corpus):
    """The `str.encode` case: unicode has it in 1.6 and string in 2.0.

    `"x".encode()` is a 2.0 feature even though the unicode table carried
    the row a release earlier, so the release the family agrees in is the
    answer and the file cited is the one that changed.
    """
    corpus("1.5", "string", [])
    corpus("1.6", "string", [])
    corpus("1.6", "unicode", ["encode"])
    corpus("2.0", "string", ["encode"])
    corpus("2.0", "unicode", ["encode"])
    record = typemethods._date_one_type("str")["str.encode"]
    assert record["added"] == "2.0"
    assert record["absent_in"] == "1.6"
    assert record["file"] == "Objects/stringobject.c"
    assert "unicodeobject.c" in record["note"]


def test_a_method_one_of_the_family_never_has_is_not_dated(corpus):
    """`isdecimal` is a unicode method the 2.x string type never had.

    So no release is the answer for `str.isdecimal`: what makes it a
    string method is 3.0 renaming unicode to `str`, which this method
    cannot see. Reported by `partial()` rather than guessed at.
    """
    corpus("1.5", "string", [])
    corpus("1.6", "string", [])
    corpus("1.6", "unicode", ["isdecimal"])
    corpus("2.0", "string", [])
    corpus("2.0", "unicode", ["isdecimal"])
    assert "str.isdecimal" not in typemethods._date_one_type("str")


def test_a_method_that_goes_away_again_is_not_dated(corpus):
    """`added` means "available ever since", which a gap contradicts."""
    corpus("1.5", "list", ["append"])
    corpus("1.6", "list", [], literals=[])
    corpus("2.0", "list", ["append"])
    assert typemethods._date_one_type("list") == {}


@pytest.mark.parametrize(
    "name", ["bytes.split", "bytearray.split", "range.index", "memoryview.tolist"]
)
def test_the_types_2_x_had_under_another_name_are_left_out(name):
    """Silence about these is a decision rather than a gap.

    The 2.x string type became `bytes` by being renamed, so reading its
    table for `bytes` would date `bytes.capitalize` to 1.6, five releases
    before anything could be spelled `b"..."`. 2.x `range` returns a
    list, so `range(3).index` in this era is `list.index`.

    The dataset dates these all the same, from the types' own arrivals
    rather than from any method table: see
    `test_every_method_of_the_types_the_tables_miss_is_dated`.
    """
    assert not typemethods.type_is_covered(name)


@pytest.mark.parametrize("name", ["dict.setdefault", "str.split", "set.add"])
def test_the_types_it_does_speak_for(name):
    assert typemethods.type_is_covered(name)
