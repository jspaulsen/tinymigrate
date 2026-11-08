import re
import shutil
import subprocess
from pathlib import Path

import pytest

import gander
from gander import GanderError, Migration, MigrationParseError, collect_migrations, parse_migration

# The real migration directories gander replaces goose-py in, copied from hearth and simulacra.
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"

# (file name, up statement count, down statement count) for every fixture file; matches what
# goose v3.28.0 executes, which `test_fixture_statements_match_what_goose_executes` checks.
HEARTH_STATEMENT_COUNTS = [
    ("00001_create_chat_log.sql", 7, 5),
    ("00002_add_card_fields_and_import.sql", 21, 5),
    ("00003_create_last_prompts.sql", 1, 1),
    ("00004_create_connections.sql", 3, 2),
    ("00005_add_runtime_settings.sql", 9, 9),
    ("00006_create_reply_prompts.sql", 3, 2),
    ("00007_add_chat_title_and_chat_deletion.sql", 3, 3),
]
SIMULACRA_STATEMENT_COUNTS = [
    ("00001_init.sql", 1, 1),
    ("00002_create_personas.sql", 2, 1),
    ("00003_create_conversations.sql", 3, 2),
    ("00004_add_persona_voice.sql", 2, 2),
]

# hearth 00001's first trigger, exactly as its StatementBegin/End block holds it.
HEARTH_UPDATE_TRIGGER = """CREATE TRIGGER events_refuse_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;"""


# Lines goose's splitter treats specially, all valid SQLite so goose runs them. goose's log drops
# `--` and empty lines, so the cross-check pins where statements split, not their text.
# The whitespace-only line is spelled `\x20` so an editor trimming trailing spaces keeps it.
GOOSE_SPLIT_EDGE_CASES = """-- leading comment
-- +goose Up
CREATE TABLE a (x INTEGER);  -- trailing comment
CREATE TABLE b (x INTEGER);--glued
CREATE TABLE c (x INTEGER); CREATE TABLE d (
    -- inner comment

    x INTEGER
);
\x20\x20\x20
-- pulled into the next statement
CREATE TABLE e (x INTEGER);

-- +goose Down
-- +goose StatementBegin
CREATE TRIGGER t BEFORE DELETE ON a
BEGIN
    SELECT RAISE(ABORT, 'no');
END;
-- +goose StatementEnd
DROP TRIGGER t;
DROP TABLE e;
DROP TABLE d;
DROP TABLE c;
DROP TABLE b;
DROP TABLE a;
"""

# How `goose -v` logs each statement it sends: grey ANSI colour around the statement text.
GOOSE_STATEMENT_PATTERN = re.compile(r"Executing statement: (.*?)\n\x1b\[00m", re.DOTALL)

# goose's `clearStatement` regexes: the log drops column-0 `--` lines and empty lines, so
# gander's statements get the same treatment before they are compared with it.
GOOSE_LOG_COMMENT_PATTERN = re.compile(r"^--.*$[\r\n]*", re.MULTILINE)
GOOSE_LOG_EMPTY_LINE_PATTERN = re.compile(r"^$[\r\n]*", re.MULTILINE)

# The file named `00001_x.sql` with a byte that is not UTF-8 (latin-1 `é`) in a comment.
NON_UTF8_MIGRATION = b"-- +goose Up\n-- caf\xe9\nSELECT 1;\n"


def _write_migration(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")

    return path


def _run_goose(directory: Path, database: Path, command: str) -> list[str]:
    result = subprocess.run(["goose", "-v", "-dir", str(directory), "sqlite3", str(database), command], capture_output=True, text=True, check=True)
    return [statement.strip() for statement in GOOSE_STATEMENT_PATTERN.findall(result.stderr)]


def _clear_statement(statement: str) -> str:
    statement = GOOSE_LOG_COMMENT_PATTERN.sub("", statement)

    return GOOSE_LOG_EMPTY_LINE_PATTERN.sub("", statement).strip()


def test_the_parser_names_are_importable_from_the_package_root() -> None:
    assert gander.Migration is Migration
    assert gander.parse_migration is parse_migration
    assert gander.collect_migrations is collect_migrations
    assert issubclass(gander.MigrationParseError, GanderError)


@pytest.mark.parametrize(("name", "up_count", "down_count"), HEARTH_STATEMENT_COUNTS)
def test_every_hearth_migration_parses_with_its_statement_counts(name: str, up_count: int, down_count: int) -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "hearth" / name)

    assert len(migration.up_statements) == up_count
    assert migration.down_statements is not None
    assert len(migration.down_statements) == down_count
    assert migration.use_transaction


@pytest.mark.parametrize(("name", "up_count", "down_count"), SIMULACRA_STATEMENT_COUNTS)
def test_every_simulacra_migration_parses_with_its_statement_counts(name: str, up_count: int, down_count: int) -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "simulacra" / name)

    assert len(migration.up_statements) == up_count
    assert migration.down_statements is not None
    assert len(migration.down_statements) == down_count
    assert migration.use_transaction


def test_a_statement_block_becomes_one_statement() -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "hearth" / "00001_create_chat_log.sql")

    assert migration.up_statements[5] == HEARTH_UPDATE_TRIGGER


def test_the_version_and_description_come_from_the_file_name() -> None:
    path = FIXTURE_DIRECTORY / "hearth" / "00004_create_connections.sql"

    migration = parse_migration(path)

    assert migration.version == 4
    assert migration.description == "create_connections"
    assert migration.path == path


def test_a_comment_before_the_up_annotation_is_ignored() -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "simulacra" / "00001_init.sql")

    assert migration.up_statements == ("SELECT 1;",)
    assert migration.down_statements == ("SELECT 1;",)


def test_a_statement_spanning_lines_keeps_its_inner_comments_and_blank_lines(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\n-- leading\n\nCREATE TABLE a (\n    -- inner\n\n    x INTEGER\n);\n")

    assert parse_migration(path).up_statements == ("CREATE TABLE a (\n    -- inner\n\n    x INTEGER\n);",)


def test_a_trailing_comment_after_the_semicolon_still_ends_the_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nCREATE TABLE a (x INTEGER);  -- note\nCREATE TABLE b (x INTEGER);\n")

    assert parse_migration(path).up_statements == ("CREATE TABLE a (x INTEGER);  -- note", "CREATE TABLE b (x INTEGER);")


def test_a_semicolon_glued_to_a_comment_does_not_end_the_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nCREATE TABLE a (x INTEGER);--note\nCREATE TABLE b (x INTEGER);\n")

    assert parse_migration(path).up_statements == ("CREATE TABLE a (x INTEGER);--note\nCREATE TABLE b (x INTEGER);",)


def test_a_semicolon_in_the_middle_of_a_line_does_not_split_the_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nCREATE TABLE a (x INTEGER); CREATE TABLE b (\n    x INTEGER\n);\n")

    assert parse_migration(path).up_statements == ("CREATE TABLE a (x INTEGER); CREATE TABLE b (\n    x INTEGER\n);",)


def test_annotations_ignore_case_and_surrounding_whitespace(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "--+goose up\nSELECT 1;\n--   +goose   DOWN  \nSELECT 2;\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("SELECT 1;",)
    assert migration.down_statements == ("SELECT 2;",)


def test_an_uppercase_goose_marker_is_an_ordinary_comment(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nSELECT 1;\n-- +GOOSE Down\nSELECT 2;\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("SELECT 1;", "SELECT 2;")
    assert migration.down_statements is None


def test_a_file_without_a_down_annotation_has_no_down_section(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nSELECT 1;\n")

    assert parse_migration(path).down_statements is None


def test_an_empty_down_section_has_no_statements(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nSELECT 1;\n-- +goose Down\n")

    assert parse_migration(path).down_statements == ()


def test_no_transaction_turns_the_transaction_off_wherever_it_appears(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose NO TRANSACTION\n-- +goose Up\nSELECT 1;\n")

    assert not parse_migration(path).use_transaction


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", r"00001_x\.sql: no '-- \+goose Up' annotation"),
        ("-- just a comment\n", r"00001_x\.sql: no '-- \+goose Up' annotation"),
        ("SELECT 1;\n-- +goose Up\n", r"00001_x\.sql:1: SQL before the '-- \+goose Up' annotation"),
        ("-- +goose Up\n-- +goose Up\n", r"00001_x\.sql:2: duplicate '-- \+goose Up' annotation"),
        ("-- +goose Down\n-- +goose Up\n", r"00001_x\.sql:1: '-- \+goose Down' before '-- \+goose Up'"),
        ("-- +goose Up\n-- +goose Down\n-- +goose Down\n", r"00001_x\.sql:3: duplicate '-- \+goose Down' annotation"),
        ("-- +goose Up\nSELECT 1\n", r"00001_x\.sql:2: statement has no terminating ';'"),
        ("-- +goose Up\nSELECT 1\n-- +goose Down\n", r"00001_x\.sql:2: statement has no terminating ';'"),
        ("-- +goose Up\nSELECT 1;\n-- +goose Down\nSELECT 2\n", r"00001_x\.sql:4: statement has no terminating ';'"),
        ("-- +goose Up\n-- +goose StatementBegin\nSELECT 1;\n", r"00001_x\.sql:2: '-- \+goose StatementBegin' without '-- \+goose StatementEnd'"),
        ("-- +goose StatementBegin\n", r"00001_x\.sql:1: '-- \+goose StatementBegin' before '-- \+goose Up'"),
        ("-- +goose Up\n-- +goose StatementBegin\n-- +goose StatementBegin\n", r"00001_x\.sql:3: nested '-- \+goose StatementBegin'"),
        ("-- +goose Up\n-- +goose StatementBegin\nSELECT 1;\n-- +goose Down\n", r"00001_x\.sql:2: '-- \+goose StatementBegin' without '-- \+goose StatementEnd'"),
        ("-- +goose Up +goose Down\n", r"00001_x\.sql:1: more than one '\+goose' in annotation"),
        ("-- +goose Up\n-- +goose StatementEnd\n", r"00001_x\.sql:2: '-- \+goose StatementEnd' without '-- \+goose StatementBegin'"),
        ("-- +goose Up\n-- +goose Sideways\n", r"00001_x\.sql:2: unknown annotation 'Sideways'"),
        ("-- +goose Up\n-- see +goose docs\n", r"00001_x\.sql:2: unknown annotation"),
        ("  -- +goose Up\n", r"00001_x\.sql:1: annotation must start at the beginning of the line"),
        ("-- +goose Up\n-- +goose ENVSUB ON\n", r"00001_x\.sql:2: annotation 'ENVSUB ON' is not supported"),
    ],
)
def test_a_malformed_file_raises_naming_the_file_and_line(tmp_path: Path, text: str, message: str) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", text)

    with pytest.raises(MigrationParseError, match=message):
        parse_migration(path)


@pytest.mark.parametrize("name", ["foo.sql", "2.sql", "0_zero.sql", "+3_plus.sql", "1a_x.sql", "9223372036854775808_too_big.sql"])
def test_a_file_name_without_a_valid_version_raises(tmp_path: Path, name: str) -> None:
    path = _write_migration(tmp_path, name, "-- +goose Up\nSELECT 1;\n")

    with pytest.raises(MigrationParseError, match=name.replace("+", r"\+")):
        parse_migration(path)


def test_collected_migrations_are_ordered_by_integer_version(tmp_path: Path) -> None:
    for name in ["10_ten.sql", "9_nine.sql", "00001_one.sql"]:
        _write_migration(tmp_path, name, "-- +goose Up\nSELECT 1;\n")

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1, 9, 10]


def test_collecting_ignores_files_that_do_not_end_in_sql(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- +goose Up\nSELECT 1;\n")
    _write_migration(tmp_path, "README.md", "not a migration")
    _write_migration(tmp_path, "00002_two.SQL", "not a migration either, as for goose")

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1]


def test_collecting_two_files_with_the_same_version_raises(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- +goose Up\nSELECT 1;\n")
    _write_migration(tmp_path, "1_also_one.sql", "-- +goose Up\nSELECT 1;\n")

    with pytest.raises(MigrationParseError, match=r"version 1 .*00001_one\.sql.*1_also_one\.sql"):
        collect_migrations(tmp_path)


def test_collecting_the_fixture_directories_returns_every_file() -> None:
    assert [migration.version for migration in collect_migrations(FIXTURE_DIRECTORY / "hearth")] == [1, 2, 3, 4, 5, 6, 7]
    assert [migration.version for migration in collect_migrations(FIXTURE_DIRECTORY / "simulacra")] == [1, 2, 3, 4]


def test_a_whitespace_only_line_makes_the_comment_after_it_part_of_the_next_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\n   \n-- c\nSELECT 1;\n")

    assert parse_migration(path).up_statements == ("-- c\nSELECT 1;",)


def test_a_comment_after_a_whitespace_only_line_at_the_end_is_an_unterminated_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nSELECT 1;\n  \n-- trailing comment\n")

    with pytest.raises(MigrationParseError, match=r"00001_x\.sql:4: statement has no terminating ';'"):
        parse_migration(path)


def test_an_empty_statement_block_yields_no_statement_and_keeps_the_next_one(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\n-- +goose StatementBegin\n-- +goose StatementEnd\nSELECT 1;\n")

    assert parse_migration(path).up_statements == ("SELECT 1;",)


def test_crlf_line_endings_parse_like_lf(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\r\nCREATE TABLE a (\r\n    x INTEGER\r\n);\r\n-- +goose Down\r\nDROP TABLE a;\r\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("CREATE TABLE a (\n    x INTEGER\n);",)
    assert migration.down_statements == ("DROP TABLE a;",)


def test_a_lone_carriage_return_inside_a_statement_is_kept(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- +goose Up\nSELECT 'a\rb';\n")

    assert parse_migration(path).up_statements == ("SELECT 'a\rb';",)


def test_a_file_that_is_not_utf8_raises_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "00001_x.sql"
    path.write_bytes(NON_UTF8_MIGRATION)

    with pytest.raises(MigrationParseError, match=r"00001_x\.sql:2: not valid UTF-8"):
        parse_migration(path)


def test_collecting_ignores_a_subdirectory_named_like_a_migration(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- +goose Up\nSELECT 1;\n")
    (tmp_path / "2_sub.sql").mkdir()

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1]


def _assert_statements_match_goose(directory: Path, database: Path) -> None:
    migrations = collect_migrations(directory)

    goose_up_statements = _run_goose(directory, database, "up")
    goose_down_statements = [statement for _ in migrations for statement in _run_goose(directory, database, "down")]

    assert goose_up_statements == [_clear_statement(statement) for migration in migrations for statement in migration.up_statements]
    assert goose_down_statements == [_clear_statement(statement) for migration in reversed(migrations) for statement in migration.down_statements or ()]


@pytest.mark.skipif(shutil.which("goose") is None, reason="goose binary not installed")
@pytest.mark.parametrize("directory_name", ["hearth", "simulacra"])
def test_fixture_statements_match_what_goose_executes(tmp_path: Path, directory_name: str) -> None:
    _assert_statements_match_goose(FIXTURE_DIRECTORY / directory_name, tmp_path / "goose.db")


@pytest.mark.skipif(shutil.which("goose") is None, reason="goose binary not installed")
def test_edge_case_statements_match_what_goose_executes(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    _write_migration(directory, "00001_edge_cases.sql", GOOSE_SPLIT_EDGE_CASES)

    _assert_statements_match_goose(directory, tmp_path / "goose.db")


@pytest.mark.parametrize("names", [[], ["README.md"]], ids=["no_files", "no_sql_files"])
def test_collecting_a_directory_with_no_migration_files_raises_naming_it(tmp_path: Path, names: list[str]) -> None:
    for name in names:
        _write_migration(tmp_path, name, "not a migration")

    with pytest.raises(MigrationParseError, match=f"no migration files found in {re.escape(str(tmp_path))}"):
        collect_migrations(tmp_path)


def test_the_parser_accepts_a_str_path() -> None:
    simulacra_directory = FIXTURE_DIRECTORY / "simulacra"

    assert [migration.version for migration in collect_migrations(str(simulacra_directory))] == [1, 2, 3, 4]
    assert parse_migration(str(simulacra_directory / "00001_init.sql")).path == simulacra_directory / "00001_init.sql"
