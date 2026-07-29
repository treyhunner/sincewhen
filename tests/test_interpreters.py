"""The decisions `interpreters.py` makes without asking an interpreter.

Building fourteen interpreters needs Docker and ten minutes, so none of
that is exercised here. What is exercised is the logic that turns their
answers into version claims, which is where a bug does the real damage:
every one of these functions can turn a working build into a wrong
version number, silently, and several already did before they were
guarded.

Three families, and the reason each one is worth a test:

- **the probe source**, which has to parse under Python 0.9.1. That rules
  out `==`, bare expression statements, and any name that was a keyword
  in 1991, and none of those failures look like failures: they look like
  a release that did not have the feature.
- **the presence mask**, which has four readings and only one of them is
  a date.
- **the absence guard**, which is the difference between this method
  being useful and being a machine for inventing wrong versions. It took
  48 false disagreements down to 1.
"""

import interpreters
import pytest

RELEASES = ("0.9", "1.0", "1.1", "1.2")


@pytest.fixture
def table(monkeypatch):
    """Install a small presence table and return a way to add to it."""
    built = {"releases": list(RELEASES), "presence": {}}
    monkeypatch.setattr(interpreters, "load_table", lambda: built)
    return built["presence"]


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


class TestDated:
    """Four readings of a presence mask, and only one is a date."""

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
