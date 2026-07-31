"""The decisions `interpreters.py` makes without asking an interpreter.

Building thirty-one interpreters needs Docker and the better part of an
hour, so none of that is exercised here. What is exercised is the logic
that turns their answers into version claims, which is where a bug does
the real damage: every one of these functions can turn a working build
into a wrong version number, silently, and several already did before
they were guarded.

Three families, and the reason each one is worth a test:

- **the probe source**, which has to parse under Python 0.9.1 at one end
  and Python 3.14 at the other. That rules out `==`, bare expression
  statements, and any name that was a keyword in 1991, and none of those
  failures look like failures: they look like a release that did not have
  the feature.
- **the presence mask**, which is read backwards from the newest release
  because the claim is "available ever since", and which has five
  readings of which only one is a date.
- **the absence guard**, which is the difference between this method
  being useful and being a machine for inventing wrong versions. It took
  48 false disagreements down to 1.
"""

import interpreters
import pytest

RELEASES = ("0.9", "1.0", "1.1", "1.2")

# A slice of the modern half, chosen so that the two releases the
# dataset's own rule forgives sit in the middle of it.
MODERN = ("2.6", "2.7", "3.0", "3.1", "3.2", "3.3")


@pytest.fixture
def table(monkeypatch):
    """Install a small presence table and return a way to add to it."""
    built = {"releases": list(RELEASES), "presence": {}}
    monkeypatch.setattr(interpreters, "load_table", lambda: built)
    return built["presence"]


@pytest.fixture
def modern_table(monkeypatch):
    """The same, over releases from the modern half of the corpus."""
    built = {"releases": list(MODERN), "presence": {}}
    monkeypatch.setattr(interpreters, "load_table", lambda: built)
    return built["presence"]


@pytest.fixture(autouse=True)
def _no_cached_trees(monkeypatch, tmp_path):
    """Point the corpus at an empty directory that exists.

    Every test here works from a fake presence table, and none of them
    should be reading the 2 GB corpus. Without this they do: `_ships_in`
    refuses outright when a release's tree is missing, so three tests
    passed only on a machine that happened to have `.cache/` populated
    and failed in CI, where the test job restores no corpus.
    """
    monkeypatch.setattr(interpreters, "source_root", lambda version: tmp_path)
    _forget()
    yield
    _forget()


def _forget():
    """Drop every cache keyed on a release, since the fakes move.

    They are keyed by release and name rather than by what the tree said,
    which is right in production, where the tree does not change under a
    run, and wrong here, where changing it is the entire point.
    """
    interpreters._ships_in.cache_clear()
    interpreters._legacy_modules.cache_clear()
    interpreters._library_root.cache_clear()
    interpreters._c_module_inits.cache_clear()


@pytest.fixture
def shipped(monkeypatch):
    """Control what each release's own source is taken to implement."""
    modules: dict[str, set[str]] = {}
    monkeypatch.setattr(
        interpreters,
        "c_module_files",
        lambda version: dict.fromkeys(modules.get(version, ()), "x.c"),
    )
    monkeypatch.setattr(interpreters, "module_paths", lambda version: {})
    monkeypatch.setattr(
        interpreters, "_ships_as_package", lambda version, module: False
    )
    _forget()
    return modules


class TestProbeSource:
    """The probe has to parse under every release, including 0.9.1."""

    def test_a_lookup_is_assigned_rather_than_evaluated(self):
        """0.9.1 echoes an expression statement even when running a script.

        A bare `math.floor` would print its own repr into the middle of
        the results, so every lookup is an assignment.
        """
        source = interpreters._probe_source(["attribute math.floor"])
        assert "    _ = math.floor" in source
        assert "\n    math.floor\n" not in source

    def test_it_ends_with_the_sentinel(self):
        """Resolving nothing and dying have to be distinguishable.

        Without this, the oldest releases look like they crashed on most
        batches, because most batches genuinely resolve nothing.
        """
        source = interpreters._probe_source(["module bisect"])
        assert source.rstrip().endswith(f"print '{interpreters.FINISHED}'")

    def test_a_keyword_is_not_asked_about(self):
        """`_ = print` is a syntax error here, not a lookup that fails.

        A syntax error is raised when the file is compiled, so one such
        name would silence every other name in the batch.
        """
        source = interpreters._probe_source(["builtin print", "builtin abs"])
        assert "_ = print" not in source
        assert "Y builtin print" not in source
        assert "_ = abs" in source

    def test_a_builtin_is_looked_up_bare(self):
        source = interpreters._probe_source(["builtin abs"])
        assert "import" not in source

    def test_a_dotted_module_is_also_tried_as_an_attribute(self):
        """Packages arrived in 1.5, and `os.path` is older than packages.

        `import os.path` is a syntax the four releases before 1.5 cannot
        run, though all of them have `os.path`.
        """
        source = interpreters._probe_source(["module os.path"])
        assert "import os.path" in source
        assert "    import os\n    _ = os.path" in source

    def test_a_nested_attribute_imports_the_package_that_holds_it(self):
        """Importing only `xml` binds nothing called `etree`."""
        source = interpreters._probe_source(["attribute xml.etree.ElementTree.parse"])
        assert "    import xml.etree.ElementTree\n" in source

    def test_an_attribute_is_tried_without_an_import_too(self):
        """`str.format` has no module to import: the head is a builtin."""
        source = interpreters._probe_source(["attribute str.format"])
        assert "try:\n    _ = str.format\n" in source

    def test_the_modern_half_prints_with_a_function(self):
        """`print 'x'` is a syntax error from 3.0, and 2.6 accepts both."""
        source = interpreters._probe_source(["module bisect"], "3.5")
        assert "print('Y module bisect')" in source
        assert "print 'Y" not in source

    def test_python_3_is_asked_about_its_own_keywords(self):
        """`print` and `exec` are names there, and names are datable.

        Skipping them everywhere would leave the two builtins that most
        obviously changed in Python 3 with nothing to say about them.
        """
        source = interpreters._probe_source(["builtin print"], "3.5")
        assert "_ = print" in source
        assert "Y builtin print" in source


class TestHealthSource:
    """0.9.1 has no `==`, so the check cannot be written the obvious way."""

    def test_the_oldest_release_compares_with_a_single_equals(self):
        source = interpreters._health_source("0.9")
        assert "chr(65) = 'A'" in source
        assert "==" not in source

    def test_every_later_release_compares_with_a_double_equals(self):
        source = interpreters._health_source("1.0")
        assert "chr(65) == 'A'" in source

    def test_it_checks_every_item_in_the_battery(self):
        source = interpreters._health_source("2.5")
        for label, *_ in interpreters.HEALTH:
            assert f"print 'H {label}'" in source

    def test_the_modern_half_checks_which_release_answered(self):
        """Seventeen prefixes side by side, so "which one is this" matters.

        Compared part by part rather than as a prefix, because 2.6 calls
        itself "2.6" with no micro and a bare "3.1" prefix matches 3.10.
        """
        source = interpreters._health_source("3.1")
        assert "sys.version.split()[0].split('.')[:2] == ['3', '1']" in source
        assert interpreters._health_source("3.10").count("['3', '10']") == 1


class TestDated:
    """Five readings of a presence mask, and only one is a date."""

    def test_absent_then_present_ever_since_is_a_date(self, table, shipped):
        table["module bisect"] = "..##"
        assert interpreters.dated("module bisect") == {
            "added": "1.1",
            "absent_in": "1.0",
            "mask": "..##",
        }

    def test_present_in_the_oldest_release_is_only_a_floor(self, table, shipped):
        """Nothing older survives to be asked, so this bounds rather than dates."""
        found = interpreters.dated("builtin abs")
        assert found is None
        table["builtin abs"] = "####"
        assert interpreters.dated("builtin abs") == {"floor": "0.9", "mask": "####"}

    def test_a_name_that_comes_back_is_reported_as_a_gap(self, table, shipped):
        table["module token"] = "#.##"
        found = interpreters.dated("module token")
        assert found is not None
        assert found["gap"] == ["1.0"]

    def test_a_name_that_goes_away_is_reported_as_removed(self, table, shipped):
        """The schema cannot record a removal, so this is not dated."""
        table["builtin cmp"] = "##.."
        found = interpreters.dated("builtin cmp")
        assert found is not None
        assert found["removed_after"] == "1.0"
        assert "added" not in found

    def test_a_name_no_release_resolves_gets_no_answer(self, table, shipped):
        assert interpreters.dated("module tomllib") is None

    def test_the_answer_is_read_from_the_newest_release_backwards(self, table, shipped):
        """ "Available ever since" is a claim about the end of the timeline.

        A name present at the start, gone, and back again is dated from
        where it came back, not from where it first appeared.
        """
        table["module argparse"] = "#..#"
        found = interpreters.dated("module argparse")
        assert found is not None
        assert found["since"] == "1.2"
        assert found["floor"] == "0.9"

    def test_a_date_the_build_cannot_support_falls_back_to_a_floor(
        self, table, shipped
    ):
        """The release that "lacks" it implements it, so the build is at fault.

        1.5, 1.6 and 2.0 install no shared modules at all, so every
        extension they ship reads as absent. Presence still proves
        presence, so the floor survives and the date does not.
        """
        table["module zlib"] = "..##"
        shipped["1.0"] = {"zlib"}
        found = interpreters.dated("module zlib")
        assert found == {"floor": "1.1", "unbuilt_in": "1.0", "mask": "..##"}


class TestForgivenReleases:
    """3.0 and 3.1 do not count against continuity, and only sometimes."""

    def test_a_gap_at_3_0_and_3_1_does_not_move_the_date(self, modern_table):
        """`argparse` shipped in 2.7 and again in 3.2, and it is 2.7.

        Nobody shipped code on 3.0 or 3.1, so a gap there is not a gap
        anyone lived through. This is the dataset's own rule, and a mask
        that spans the whole history is what makes it computable.
        """
        modern_table["module argparse"] = ".#..##"
        assert interpreters.dated("module argparse") == {
            "added": "2.7",
            "absent_in": "2.6",
            "mask": ".#..##",
        }

    def test_the_gap_is_only_forgiven_where_the_older_side_has_it(self, modern_table):
        """Absent from 2.7, 3.0 and 3.1 means the answer is 3.2.

        Reading the gap as continuous regardless would date such a name
        to 3.0, a release it demonstrably could not be used in.
        """
        modern_table["module unittest.mock"] = "....##"
        assert interpreters.dated("module unittest.mock") == {
            "added": "3.2",
            "absent_in": "3.1",
            "mask": "....##",
        }

    def test_a_removal_is_not_bridged_either(self, modern_table):
        """A name Python 3 dropped has no continuity to preserve.

        Forgiving the gap on the strength of the older side alone
        reported `repr` as last seen in 3.1, a release that never had it.
        """
        modern_table["module repr"] = "##...."
        found = interpreters.dated("module repr")
        assert found is not None
        assert found["removed_after"] == "2.7"


class TestUnanswered:
    """ "Could not be asked" is not "absent", and the table records which."""

    def test_a_name_that_killed_the_interpreter_dates_nothing(
        self, modern_table, monkeypatch
    ):
        """The 3.5 build segfaults on `import uuid`, and 3.5 still has it.

        Read as an absence this dates `uuid.NAMESPACE_DNS` to 3.7, five
        releases after the release that shipped it.
        """
        built = {
            "releases": list(MODERN),
            "presence": {"attribute uuid.NAMESPACE_DNS": "###..#"},
            "unanswered": {"3.1": ["attribute uuid.NAMESPACE_DNS"]},
        }
        monkeypatch.setattr(interpreters, "load_table", lambda: built)
        assert not interpreters.absence_is_real("3.1", "attribute uuid.NAMESPACE_DNS")
        assert interpreters.absence_is_real("3.2", "attribute uuid.NAMESPACE_DNS")

    def test_a_builtin_is_not_exempt_from_it(self):
        """A builtin's absence is otherwise always real, and a crash is not one."""
        built = {
            "releases": list(MODERN),
            "presence": {"builtin print": "...###"},
            "unanswered": {"2.7": ["builtin print"]},
        }
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(interpreters, "load_table", lambda: built)
            assert not interpreters.absence_is_real("2.7", "builtin print")
            assert interpreters.absence_is_real("2.6", "builtin print")

    def test_a_keyword_is_unaskable_rather_than_absent(self):
        """`print` cannot be spelled as a name before 3.0, so nobody asked.

        Left to fall through it wrote sixteen leading absences and dated
        `print` to 3.0 against a 2.7 the probe never put a question to.
        """
        targets = ["builtin print", "builtin abs"]
        assert interpreters._unaskable(targets, "2.7") == {"builtin print"}
        assert interpreters._unaskable(targets, "3.0") == set()


class TestShipsIn:
    """Whether a release's own tree implements a module, per era."""

    def test_the_modern_half_reads_the_library_by_path(self, tmp_path, monkeypatch):
        """A dotted name is a path there, which the old reading cannot spell."""
        library = tmp_path / "Python-3.3.0" / "Lib"
        (library / "unittest").mkdir(parents=True)
        (library / "unittest" / "__init__.py").touch()
        (library / "unittest" / "mock.py").touch()
        monkeypatch.setattr(interpreters, "source_root", lambda version: tmp_path)
        _forget()
        assert interpreters._ships_in("3.3", "unittest.mock")
        assert not interpreters._ships_in("3.3", "unittest.doesnotexist")

    def test_a_modern_c_module_is_found_by_its_init_function(
        self, tmp_path, monkeypatch
    ):
        """`PyInit_<name>` is what the import protocol looks for.

        That is what makes reading it safe where reading a bare function
        name is not: `initall()` once dated a builtin called `all` to
        1991, because it was a function name and not a module name.
        """
        modules = tmp_path / "Python-3.3.0" / "Modules"
        modules.mkdir(parents=True)
        (modules / "zlibmodule.c").write_text("PyMODINIT_FUNC\nPyInit_zlib(void)\n{}\n")
        monkeypatch.setattr(interpreters, "source_root", lambda version: tmp_path)
        _forget()
        assert interpreters._ships_in("3.3", "zlib")
        assert not interpreters._ships_in("3.3", "tomllib")


class TestAbsenceIsReal:
    """Whether a release lacking a name says anything about that release."""

    def test_a_builtin_absence_is_always_real(self, table, shipped):
        """Builtins are compiled in, so nothing external can hide one."""
        shipped["1.0"] = {"abs"}
        assert interpreters.absence_is_real("1.0", "builtin abs")

    def test_a_module_the_release_implements_is_a_build_gap(self, table, shipped):
        shipped["1.0"] = {"zlib"}
        assert not interpreters.absence_is_real("1.0", "module zlib")

    def test_a_module_the_release_lacks_is_a_real_absence(self, table, shipped):
        assert interpreters.absence_is_real("1.0", "module zlib")

    def test_a_member_is_real_when_its_module_imported(self, table, shipped):
        """`operator` imports in 1.4, so a member missing there really was.

        This is what a coarser guard got wrong: it saw `operator.c` in the
        tree and threw away 67 sound dates along with the unsound ones.
        """
        shipped["1.1"] = {"operator"}
        table["module operator"] = "..##"
        assert interpreters.absence_is_real("1.1", "attribute operator.contains")

    def test_a_member_of_a_module_that_never_imported_is_not_real(self, table, shipped):
        shipped["1.1"] = {"zlib"}
        table["module zlib"] = "...#"
        assert not interpreters.absence_is_real("1.1", "attribute zlib.compress")

    def test_a_module_with_no_entry_is_judged_by_its_members(self, table, shipped):
        """Not every module the dataset mentions has an entry of its own."""
        shipped["1.1"] = {"posix"}
        table["attribute posix.getcwd"] = ".###"
        assert interpreters.absence_is_real("1.1", "attribute posix.stat")


class TestRecipe:
    """What gets built how, which the table records so a claim is auditable."""

    def test_the_kr_era_is_built_for_i386(self):
        """Built 64-bit, 1.0 and 1.1 segfault in `chr()`."""
        assert interpreters.compiler("1.4") == "gcc -m32"
        assert "-std=gnu89" in interpreters.flags("1.4")

    def test_the_ansi_era_is_built_native(self):
        assert interpreters.compiler("1.5") == "gcc"
        assert "-std=gnu89" not in interpreters.flags("1.5")

    def test_the_recipe_names_every_patch_applied(self):
        recorded = interpreters.recipe("1.1")
        assert any("getline" in note for note in recorded)
        assert any("crypt" in note for note in recorded)

    def test_a_release_needing_no_patch_records_only_its_flags(self):
        assert not [note for note in interpreters.recipe("2.5") if "getline" in note]


class TestHarvest:
    def test_only_answer_lines_are_collected(self):
        """An interpreter's own chatter is not an answer.

        0.9.1 in particular writes tracebacks and prompts to stdout.
        """
        assert interpreters._harvest(
            "Unhandled exception: undefined name: os\nY module sys\nY module string\n"
        ) == {"module sys", "module string"}
