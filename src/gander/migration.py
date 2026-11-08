import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from gander.errors import MigrationParseError

# A file name is a version, `_`, then a description; `2.sql` and a signed `+3_x.sql` are rejected.
_FILE_NAME_PATTERN = re.compile(r"(?P<version>[0-9]+)_(?P<description>.*)\.sql")

# SQLite stores `version_id` as a signed 64-bit integer.
_MAX_VERSION = 2**63 - 1

# The markers, each a whole line compared after stripping whitespace and case-folding.
_UP_MARKER = "-- up"
_DOWN_MARKER = "-- down"
_NO_TRANSACTION_MARKER = "-- no transaction"


@dataclass(frozen=True)
class Migration:
    """
    A parsed migration file: its version and the statements of each direction.

    `down_statements` is `None` when the file has no `-- down` marker, and an empty tuple
    when it has one with nothing under it.
    """

    version: int
    description: str
    path: Path
    up_statements: tuple[str, ...]
    down_statements: tuple[str, ...] | None
    use_transaction: bool


def parse_migration(path: str | Path) -> Migration:
    """
    Parse one SQL migration file.

    A statement is the lines accumulated until `sqlite3.complete_statement` accepts them,
    so a trigger body's `;` does not end it; comment-only leftovers are dropped. Both
    directions are parsed, so a malformed down section raises too. Raises
    `MigrationParseError` naming the file, and the line where there is one.
    """
    path = Path(path)
    version, description = _parse_file_name(path)
    up_statements: list[str] | None = None
    down_statements: list[str] | None = None
    current: list[str] | None = None
    use_transaction = True
    buffer: list[str] = []
    buffer_line_number = 0

    for line_number, line in enumerate(_read_lines(path), start=1):
        stripped = line.strip()
        marker = stripped.casefold()
        if marker == _NO_TRANSACTION_MARKER:
            if current is not None:
                raise MigrationParseError(f"{path}:{line_number}: '{_NO_TRANSACTION_MARKER}' marker after '{_UP_MARKER}'")
            use_transaction = False
        elif marker == _UP_MARKER:
            if current is not None:
                raise MigrationParseError(f"{path}:{line_number}: duplicate '{_UP_MARKER}' marker")
            up_statements = current = []
        elif marker == _DOWN_MARKER:
            if current is None:
                raise MigrationParseError(f"{path}:{line_number}: '{_DOWN_MARKER}' marker before '{_UP_MARKER}'")
            if down_statements is not None:
                raise MigrationParseError(f"{path}:{line_number}: duplicate '{_DOWN_MARKER}' marker")
            _check_section_end(path, buffer, buffer_line_number)
            buffer = []
            down_statements = current = []
        elif current is None:
            if stripped and not stripped.startswith("--"):
                raise MigrationParseError(f"{path}:{line_number}: SQL before the '{_UP_MARKER}' marker")
        elif buffer or stripped:
            if not buffer:
                buffer_line_number = line_number
            buffer.append(line)
            if sqlite3.complete_statement(statement := "\n".join(buffer)):
                current.append(statement.strip())
                buffer = []

    if up_statements is None:
        raise MigrationParseError(f"{path}: no '{_UP_MARKER}' marker")
    _check_section_end(path, buffer, buffer_line_number)

    return Migration(
        version=version,
        description=description,
        path=path,
        up_statements=tuple(up_statements),
        down_statements=None if down_statements is None else tuple(down_statements),
        use_transaction=use_transaction,
    )


def collect_migrations(directory: str | Path) -> list[Migration]:
    """
    Parse every `.sql` file in a directory, ordered by integer version.

    Other files and subdirectories are ignored. Raises `MigrationParseError` when
    `directory` is missing or not a directory, a file is malformed, two files share a
    version or there is no `.sql` file.
    """
    directory = Path(directory)
    try:
        paths = sorted(path for path in directory.iterdir() if path.suffix == ".sql" and path.is_file())
    except FileNotFoundError as error:
        raise MigrationParseError(f"migration directory {directory} does not exist") from error
    except NotADirectoryError as error:
        raise MigrationParseError(f"migration directory {directory} is not a directory") from error
    if not paths:
        raise MigrationParseError(f"no migration files found in {directory}")
    migrations: dict[int, Migration] = {}
    for path in paths:
        migration = parse_migration(path)
        if (existing := migrations.get(migration.version)) is not None:
            raise MigrationParseError(f"version {migration.version} is used by both {existing.path} and {path}")
        migrations[migration.version] = migration

    return [migrations[version] for version in sorted(migrations)]


def _parse_file_name(path: Path) -> tuple[int, str]:
    match = _FILE_NAME_PATTERN.fullmatch(path.name)
    if match is None:
        raise MigrationParseError(f"{path}: file name must be '<version>_<description>.sql'")
    version = int(match["version"])
    if version < 1:
        raise MigrationParseError(f"{path}: version must be greater than zero")
    if version > _MAX_VERSION:
        raise MigrationParseError(f"{path}: version must be at most {_MAX_VERSION}")

    return version, match["description"]


def _read_lines(path: Path) -> list[str]:
    # Decoded by hand rather than with `read_text`, whose universal newlines would turn a
    # lone `\r` inside a string literal into `\n`; only the `\r` of a `\r\n` is dropped.
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        line_number = data.count(b"\n", 0, error.start) + 1
        raise MigrationParseError(f"{path}:{line_number}: not valid UTF-8 ({error.reason} at byte {error.start})") from error

    return [line.removesuffix("\r") for line in text.split("\n")]


def _check_section_end(path: Path, buffer: list[str], buffer_line_number: int) -> None:
    if any(line.strip() and not line.strip().startswith("--") for line in buffer):
        raise MigrationParseError(f"{path}:{buffer_line_number}: incomplete statement, expected it to end with ';'")
