"""Tests for reading a module's members out of the doc archives.

The markup changed under every one of these extractors, and each change
cost members silently rather than loudly: a regex that stops matching
reports an empty module, not an error. So the shapes are pinned here,
one test per shape, with the release each came out of named.

The cached archives are 500 MB and are not a test dependency, so these
run against the markup rather than against the corpus.
"""

import modindex
import pytest
from modindex import (
    MEMBER_HTML,
    MEMBER_NAMED_HTML,
    MEMBER_ROLES,
    TT_CLASS,
    _members_from_latex,
    _page_modules,
    members_in,
)


def members(text):
    """The `module.member` names one page's markup yields."""
    found = {
        f"{match['module']}.{match['name']}"
        for match in MEMBER_NAMED_HTML.finditer(text)
    }
    for match in MEMBER_HTML.finditer(text):
        role = TT_CLASS.search(match["attrs"])
        if (role["role"].lower() if role else "") in MEMBER_ROLES:
            found.add(match["name"])
    return found


def test_reads_the_1_2_shape_which_names_the_module_inline():
    """The signature sits between the name and the dash.

    Anchoring on `</B> --` skipped every member with an argument list,
    which is why 1.2 yielded its data and none of its functions.
    """
    page = (
        "<DL><DT><B>acos</B> (<VAR>x</VAR>) -- function of module math<DD>\n"
        "<DL><DT><B>pi</B> -- data of module math<DD>\n"
    )
    assert members(page) == {"math.acos", "math.pi"}


def test_ignores_an_object_member_in_the_1_2_shape():
    """These builds say what a name belongs to, and it is not a module."""
    page = (
        "<DL><DT><B>seek</B> -- method of file object<DD>\n"
        "<DL><DT><B>group</B> -- attribute of regex<DD>\n"
    )
    assert members(page) == set()


def test_reads_the_1_5_shape_with_an_unquoted_class():
    page = '<dl><dt><b><a name="l2h-711"><tt class=function>acos</tt></a></b>\n'
    assert members(page) == {"acos"}


def test_reads_the_2_3_shape_where_the_signature_moved_into_a_table():
    """The change that made 2.2 yield 1456 members and 2.3 only 476.

    Everything with an argument list was wrapped in a one-row table so
    it could wrap, which moved the bold out from under the `<dt>`.
    """
    page = (
        '<dl><dt><table cellpadding="0" cellspacing="0"><tr valign="baseline">\n'
        '  <td><nobr><b><a name="l2h-1093">'
        '<tt class="function">acos</tt></a></b>(</nobr></td>\n'
    )
    assert members(page) == {"acos"}


def test_reads_the_2_5_shape_where_the_class_is_not_the_first_attribute():
    page = (
        "  <td><nobr><b><tt id='l2h-923' xml:id='l2h-923' "
        'class="function">ceil</tt></b>(</nobr></td>\n'
    )
    assert members(page) == {"ceil"}


def test_reads_a_bare_tt_as_data():
    page = '<dt><b><a name="l2h-1334"><tt>name</tt></a></b>\n'
    assert members(page) == {"name"}


def test_reads_a_typelabel_prefix():
    page = (
        '<dl><dt><b><span class="typelabel">exception</span>&nbsp;'
        '<a name="l2h-1333"><tt class="exception">error</tt></a></b>\n'
    )
    assert members(page) == {"error"}


def test_ignores_a_method_of_an_object_on_the_modules_own_pages():
    """`socket-objects.html` hangs under `module-socket.html`.

    Every name on it is a method of a socket rather than of `socket`,
    and the only thing that says so is the descriptor class.
    """
    page = '<dl><dt><b><a name="l2h-1892"><tt class="method">accept</tt></a></b>\n'
    assert members(page) == set()


def test_ignores_an_opcode():
    page = '<dt><b><tt class="opcode">POP_TOP</tt></b>\n'
    assert members(page) == set()


def page(tmp_path, name, parent=None):
    link = f'<link rel="parent" href="{parent}.html" />' if parent else ""
    path = tmp_path / f"{name}.html"
    path.write_text(f"<html><head>{link}</head></html>", encoding="utf-8")
    return path


def test_a_continuation_page_belongs_to_the_module_it_hangs_under(tmp_path):
    """`os.listdir` is on `os-file-dir.html` and nowhere else."""
    pages = [
        page(tmp_path, "module-os"),
        page(tmp_path, "os-file-dir", parent="module-os"),
    ]
    owners = _page_modules(pages)
    assert {path.stem: module for path, module in owners.items()} == {
        "module-os": "os",
        "os-file-dir": "os",
    }


def test_the_parent_chain_is_walked_rather_than_the_one_link_read(tmp_path):
    pages = [
        page(tmp_path, "module-os"),
        page(tmp_path, "os-process", parent="module-os"),
        page(tmp_path, "os-exit-codes", parent="os-process"),
    ]
    assert _page_modules(pages)[pages[-1]] == "os"


def test_a_page_under_no_module_belongs_to_nothing(tmp_path):
    pages = [page(tmp_path, "genindex"), page(tmp_path, "about", parent="genindex")]
    assert _page_modules(pages) == {}


def test_a_parent_cycle_terminates(tmp_path):
    """A malformed build must not hang the extractor."""
    pages = [page(tmp_path, "a", parent="b"), page(tmp_path, "b", parent="a")]
    assert _page_modules(pages) == {}


LATEX = r"""
\subsection{Built-in Module {\tt sys}}
\funcitem{argv}
\funcitem{ps1,~ps2}
\funcitem{stdin, stdout, stderr}
\subsubsection{Window Object Methods}
\funcitem{close}
\section{Standard Module {\tt math}}
\begin{funcdesc}{acos}{x}
\funcline{asin}{x}
\dataline{pi}
"""


def test_reads_the_latex_descriptors():
    """0.9.1 writes `\\funcitem` and 1.4 writes `\\funcline`.

    A run of related names is one descriptor and a list of
    continuations, and 0.9.1 will put several names in one set of
    braces, so `ps1,~ps2` is two members and not one.
    """
    assert _members_from_latex(LATEX) == {
        "sys.argv",
        "sys.ps1",
        "sys.ps2",
        "sys.stdin",
        "sys.stdout",
        "sys.stderr",
        "math.acos",
        "math.asin",
        "math.pi",
    }


def test_a_heading_that_is_not_a_module_closes_the_one_before_it():
    """0.9.1 documents `stdwin` and then its window objects in place."""
    assert "sys.close" not in _members_from_latex(LATEX)


# A doc build in miniature: a module page, a continuation page hanging
# under it, and an index page belonging to nothing. Between them these
# three cover every decision `members_in` makes about a page.
MODULE_PAGE_HTML = """\
<html><head></head><body>
<dl><dt><b><a name="l2h-1"><tt class="function">gethostname</tt></a></b>()
<dl><dt><b><a name="l2h-2"><tt class="exception">error</tt></a></b>
<dl><dt><b><a name="l2h-3"><tt>AF_INET</tt></a></b>
</body></html>
"""

CONTINUATION_HTML = """\
<html><head><link rel="up" href="module-socket.html"></head><body>
<dl><dt><b><a name="l2h-4"><tt class="function">socketpair</tt></a></b>()
<dl><dt><b><a name="l2h-5"><tt class="method">accept</tt></a></b>()
</body></html>
"""

ORPHAN_HTML = """\
<html><head></head><body>
<dl><dt><b><a name="l2h-6"><tt class="function">nowhere</tt></a></b>()
</body></html>
"""


@pytest.fixture
def build(tmp_path, monkeypatch):
    """A fake HTML doc build `members_in` will read as a release."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "module-socket.html").write_text(MODULE_PAGE_HTML, encoding="utf-8")
    (lib / "socket-objects.html").write_text(CONTINUATION_HTML, encoding="utf-8")
    (lib / "genindex.html").write_text(ORPHAN_HTML, encoding="utf-8")
    monkeypatch.setattr(modindex, "html_root", lambda version: tmp_path)
    members_in.cache_clear()
    yield tmp_path
    members_in.cache_clear()


def test_members_in_reads_a_whole_module(build):
    """The end-to-end shape, which the regex tests cannot speak for.

    Every one of these would pass the shape tests above and still be
    wrong here: dropping the role filter admits `accept`, reverting the
    parent-link walk loses `socketpair`, and reading a page with no owner
    admits `nowhere`.
    """
    assert members_in("fake") == {
        "socket.gethostname",
        "socket.error",
        "socket.AF_INET",
        "socket.socketpair",
    }
