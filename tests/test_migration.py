import re
from pathlib import Path

import pytest

import gander
from gander import GanderError, Migration, MigrationParseError, collect_migrations, parse_migration

# The real migration directories gander replaces goose-py in, copied from hearth and simulacra.
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"

# (file name, up statement count, down statement count) for every fixture file, as the
# files ran under goose before they were converted to gander's syntax.
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

# hearth 00001's first trigger, whose body holds a `;` of its own.
HEARTH_UPDATE_TRIGGER = """CREATE TRIGGER events_refuse_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;"""

# The file named `00001_x.sql` with a byte that is not UTF-8 (latin-1 `é`) in a comment.
NON_UTF8_MIGRATION = b"-- up\n-- caf\xe9\nSELECT 1;\n"


def _write_migration(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")

    return path


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


def test_a_trigger_body_with_semicolons_is_one_statement_without_markers() -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "hearth" / "00001_create_chat_log.sql")

    assert migration.up_statements[5] == HEARTH_UPDATE_TRIGGER


def test_the_version_and_description_come_from_the_file_name() -> None:
    path = FIXTURE_DIRECTORY / "hearth" / "00004_create_connections.sql"

    migration = parse_migration(path)

    assert migration.version == 4
    assert migration.description == "create_connections"
    assert migration.path == path


def test_comments_and_blank_lines_before_the_up_marker_are_ignored() -> None:
    migration = parse_migration(FIXTURE_DIRECTORY / "simulacra" / "00001_init.sql")

    assert migration.up_statements == ("SELECT 1;",)
    assert migration.down_statements == ("SELECT 1;",)


def test_a_statement_keeps_the_comments_and_blank_lines_inside_and_before_it(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\n\n-- leading\nCREATE TABLE a (\n    -- inner\n\n    x INTEGER\n);\n")

    assert parse_migration(path).up_statements == ("-- leading\nCREATE TABLE a (\n    -- inner\n\n    x INTEGER\n);",)


def test_a_trailing_comment_after_the_semicolon_stays_with_its_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nCREATE TABLE a (x INTEGER);  -- note\nCREATE TABLE b (x INTEGER);--glued\n")

    assert parse_migration(path).up_statements == ("CREATE TABLE a (x INTEGER);  -- note", "CREATE TABLE b (x INTEGER);--glued")


def test_a_semicolon_inside_a_string_literal_does_not_end_the_statement(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nINSERT INTO a VALUES ('x;\ny');\n")

    assert parse_migration(path).up_statements == ("INSERT INTO a VALUES ('x;\ny');",)


def test_a_comment_only_piece_at_the_end_of_a_section_is_dropped(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nSELECT 1;\n\n-- trailing\n-- down\nSELECT 2;\n  \n-- trailing\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("SELECT 1;",)
    assert migration.down_statements == ("SELECT 2;",)


def test_markers_ignore_case_and_surrounding_whitespace(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "  -- NO Transaction \n-- UP\nSELECT 1;\n\t-- Down  \nSELECT 2;\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("SELECT 1;",)
    assert migration.down_statements == ("SELECT 2;",)
    assert not migration.use_transaction


@pytest.mark.parametrize("comment", ["-- up and down", "--down", "-- downgrade", "-- see +goose docs"])
def test_any_other_comment_is_just_a_comment(tmp_path: Path, comment: str) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", f"-- up\nSELECT 1;\n{comment}\nSELECT 2;\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("SELECT 1;", f"{comment}\nSELECT 2;")
    assert migration.down_statements is None


def test_a_file_without_a_down_marker_has_no_down_section(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nSELECT 1;\n")

    assert parse_migration(path).down_statements is None


def test_an_empty_up_section_has_no_statements(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\n-- down\nSELECT 1;\n")

    assert parse_migration(path).up_statements == ()


def test_a_utf8_byte_order_mark_is_ignored(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "\ufeff-- up\nSELECT 1;\n")

    assert parse_migration(path).up_statements == ("SELECT 1;",)


def test_a_bad_byte_after_a_byte_order_mark_is_reported_at_its_line(tmp_path: Path) -> None:
    path = tmp_path / "00001_x.sql"
    path.write_bytes(b"\xef\xbb\xbf-- up\n\xe9SELECT 1;\n")

    with pytest.raises(MigrationParseError, match=r"00001_x\.sql:2: not valid UTF-8 .* at byte 9"):
        parse_migration(path)


def test_parsing_a_missing_file_raises_naming_it(tmp_path: Path) -> None:
    with pytest.raises(MigrationParseError, match=r"00001_x\.sql: cannot read the migration file") as raised:
        parse_migration(tmp_path / "00001_x.sql")

    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_an_empty_down_section_has_no_statements(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nSELECT 1;\n-- down\n")

    assert parse_migration(path).down_statements == ()


def test_no_transaction_before_the_up_marker_turns_the_transaction_off(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- a comment\n-- no transaction\n\n-- up\nSELECT 1;\n")

    assert not parse_migration(path).use_transaction


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", r"00001_x\.sql: no '-- up' marker"),
        ("-- just a comment\n", r"00001_x\.sql: no '-- up' marker"),
        ("SELECT 1;\n-- up\n", r"00001_x\.sql:1: SQL before the '-- up' marker"),
        ("/* block */\n-- up\n", r"00001_x\.sql:1: SQL before the '-- up' marker"),
        ("-- up\n-- up\n", r"00001_x\.sql:2: duplicate '-- up' marker"),
        ("-- down\n-- up\n", r"00001_x\.sql:1: '-- down' marker before '-- up'"),
        ("-- up\n-- down\n-- down\n", r"00001_x\.sql:3: duplicate '-- down' marker"),
        ("-- up\n-- no transaction\n", r"00001_x\.sql:2: '-- no transaction' marker after '-- up'"),
        ("-- up\nSELECT 1\n", r"00001_x\.sql:2: incomplete statement"),
        ("-- up\n\nSELECT 1\n-- down\n", r"00001_x\.sql:4: '-- down' marker inside the statement that starts at line 3"),
        ("-- up\nSELECT 'a\n-- down\nb';\n", r"00001_x\.sql:3: '-- down' marker inside the statement that starts at line 2"),
        ("-- up\nCREATE TRIGGER t BEFORE DELETE ON a\nBEGIN\n    SELECT 1;\n  -- UP\nEND;\n", r"00001_x\.sql:5: '-- UP' marker inside the statement that starts at line 2"),
        ("-- up\n-- down\n-- no transaction\n", r"00001_x\.sql:3: '-- no transaction' marker after '-- up'"),
        ("-- up\nSELECT 1;\n/* c */\n", r"00001_x\.sql:3: incomplete statement"),
        ("-- up\nSELECT 1;\n-- create b\nCREATE TABLE b (\n", r"00001_x\.sql:4: incomplete statement"),
        ("-- +goose Up\nSELECT 1;\n", r"00001_x\.sql:1: goose annotation '-- \+goose Up', expected one of -- up, -- down, -- no transaction"),
        ("-- up\nSELECT 1;\n  --  +GOOSE Down \nDROP TABLE a;\n", r"00001_x\.sql:3: goose annotation '--  \+GOOSE Down'"),
        ("-- up\n-- +goose StatementBegin\n", r"00001_x\.sql:2: goose annotation"),
        ("-- up\nSELECT 1;\n-- down\nSELECT 2\n", r"00001_x\.sql:4: incomplete statement"),
        ("-- up\nSELECT 'a;\n", r"00001_x\.sql:2: incomplete statement"),
        ("-- up\nCREATE TRIGGER t BEFORE DELETE ON a\nBEGIN\n    SELECT 1;\n", r"00001_x\.sql:2: incomplete statement"),
    ],
)
def test_a_malformed_file_raises_naming_the_file_and_line(tmp_path: Path, text: str, message: str) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", text)

    with pytest.raises(MigrationParseError, match=message):
        parse_migration(path)


@pytest.mark.parametrize("name", ["foo.sql", "2.sql", "0_zero.sql", "+3_plus.sql", "1a_x.sql", "9223372036854775808_too_big.sql"])
def test_a_file_name_without_a_valid_version_raises(tmp_path: Path, name: str) -> None:
    path = _write_migration(tmp_path, name, "-- up\nSELECT 1;\n")

    with pytest.raises(MigrationParseError, match=re.escape(name)):
        parse_migration(path)


def test_collected_migrations_are_ordered_by_integer_version(tmp_path: Path) -> None:
    for name in ["10_ten.sql", "9_nine.sql", "00001_one.sql"]:
        _write_migration(tmp_path, name, "-- up\nSELECT 1;\n")

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1, 9, 10]


def test_collecting_ignores_files_that_do_not_end_in_sql(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- up\nSELECT 1;\n")
    _write_migration(tmp_path, "README.md", "not a migration")
    _write_migration(tmp_path, "00002_two.SQL", "not a migration either")

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1]


def test_collecting_ignores_a_subdirectory_named_like_a_migration(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- up\nSELECT 1;\n")
    (tmp_path / "2_sub.sql").mkdir()

    assert [migration.version for migration in collect_migrations(tmp_path)] == [1]


def test_collecting_two_files_with_the_same_version_raises(tmp_path: Path) -> None:
    _write_migration(tmp_path, "00001_one.sql", "-- up\nSELECT 1;\n")
    _write_migration(tmp_path, "1_also_one.sql", "-- up\nSELECT 1;\n")

    with pytest.raises(MigrationParseError, match=r"version 1 .*00001_one\.sql.*1_also_one\.sql"):
        collect_migrations(tmp_path)


def test_collecting_the_fixture_directories_returns_every_file() -> None:
    assert [migration.version for migration in collect_migrations(FIXTURE_DIRECTORY / "hearth")] == [1, 2, 3, 4, 5, 6, 7]
    assert [migration.version for migration in collect_migrations(FIXTURE_DIRECTORY / "simulacra")] == [1, 2, 3, 4]


@pytest.mark.parametrize("names", [[], ["README.md"]], ids=["no_files", "no_sql_files"])
def test_collecting_a_directory_with_no_migration_files_raises_naming_it(tmp_path: Path, names: list[str]) -> None:
    for name in names:
        _write_migration(tmp_path, name, "not a migration")

    with pytest.raises(MigrationParseError, match=f"no migration files found in {re.escape(str(tmp_path))}"):
        collect_migrations(tmp_path)


def test_collecting_a_missing_directory_raises_naming_it(tmp_path: Path) -> None:
    directory = tmp_path / "nope"

    with pytest.raises(MigrationParseError, match=f"migration directory {re.escape(str(directory))} does not exist") as raised:
        collect_migrations(directory)

    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_collecting_a_file_instead_of_a_directory_raises_naming_it(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nSELECT 1;\n")

    with pytest.raises(MigrationParseError, match=f"migration directory {re.escape(str(path))} is not a directory") as raised:
        collect_migrations(path)

    assert isinstance(raised.value.__cause__, NotADirectoryError)


def test_crlf_line_endings_parse_like_lf(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\r\nCREATE TABLE a (\r\n    x INTEGER\r\n);\r\n-- down\r\nDROP TABLE a;\r\n")

    migration = parse_migration(path)

    assert migration.up_statements == ("CREATE TABLE a (\n    x INTEGER\n);",)
    assert migration.down_statements == ("DROP TABLE a;",)


def test_a_lone_carriage_return_inside_a_statement_is_kept(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "00001_x.sql", "-- up\nSELECT 'a\rb';\n")

    assert parse_migration(path).up_statements == ("SELECT 'a\rb';",)


def test_a_file_that_is_not_utf8_raises_naming_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "00001_x.sql"
    path.write_bytes(NON_UTF8_MIGRATION)

    with pytest.raises(MigrationParseError, match=r"00001_x\.sql:2: not valid UTF-8"):
        parse_migration(path)


def test_the_parser_accepts_a_str_path() -> None:
    simulacra_directory = FIXTURE_DIRECTORY / "simulacra"

    assert [migration.version for migration in collect_migrations(str(simulacra_directory))] == [1, 2, 3, 4]
    assert parse_migration(str(simulacra_directory / "00001_init.sql")).path == simulacra_directory / "00001_init.sql"
