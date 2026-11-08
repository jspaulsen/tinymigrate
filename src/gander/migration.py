import re
from dataclasses import dataclass
from pathlib import Path

from gander.errors import MigrationParseError

# goose's file name rule: a version, `_`, then a description. goose rejects `2.sql` for
# its missing `_`; unlike goose's `strconv.ParseInt`, a sign (`+3_x.sql`) is rejected too.
_FILE_NAME_PATTERN = re.compile(r"(?P<version>[0-9]+)_(?P<description>.*)\.sql")

# goose parses versions as int64 and SQLite stores `version_id` as a signed 64-bit integer.
_MAX_VERSION = 2**63 - 1

# The annotations goose v3.28.0 knows, spelled as goose spells them; matched case-insensitively.
_UP = "Up"
_DOWN = "Down"
_STATEMENT_BEGIN = "StatementBegin"
_STATEMENT_END = "StatementEnd"
_NO_TRANSACTION = "NO TRANSACTION"
_ANNOTATIONS = (_UP, _DOWN, _STATEMENT_BEGIN, _STATEMENT_END, _NO_TRANSACTION)

# goose's environment-variable substitution annotations, which gander does not implement.
_UNSUPPORTED_ANNOTATIONS = ("ENVSUB ON", "ENVSUB OFF")


@dataclass(frozen=True)
class Migration:
    """
    A parsed migration file: its version and the statements of each direction.

    `down_statements` is `None` when the file has no `-- +goose Down` annotation, and an
    empty tuple when it has one with nothing under it.
    """

    version: int
    description: str
    path: Path
    up_statements: tuple[str, ...]
    down_statements: tuple[str, ...] | None
    use_transaction: bool


def parse_migration(path: Path) -> Migration:
    """
    Parse one goose-style SQL migration file.

    Splits statements as goose v3.28.0 does: a statement ends at a line whose last word
    before any `--` comment ends in `;`, and a `StatementBegin`/`StatementEnd` block is
    one statement. Both directions are parsed, so a malformed Down section raises too.
    Raises `MigrationParseError` naming the file, and the line where there is one.
    """
    version, description = _parse_file_name(path)
    up_statements: list[str] = []
    down_statements: list[str] | None = None
    current: list[str] | None = None
    use_transaction = True
    in_block = False
    block_line_number = 0
    buffer: list[str] = []
    buffer_line_number = 0

    for line_number, line in enumerate(_read_lines(path), start=1):
        stripped = line.strip()
        if current is None and not stripped:
            continue
        if stripped.startswith("--") and "+goose" in line:
            annotation = _parse_annotation(path, line_number, line)
            if annotation == _UP:
                if current is not None:
                    raise MigrationParseError(f"{path}:{line_number}: duplicate '-- +goose Up' annotation")
                current = up_statements
            elif annotation == _DOWN:
                if current is None:
                    raise MigrationParseError(f"{path}:{line_number}: '-- +goose Down' before '-- +goose Up'")
                if in_block:
                    raise MigrationParseError(f"{path}:{block_line_number}: '-- +goose StatementBegin' without '-- +goose StatementEnd'")
                if down_statements is not None:
                    raise MigrationParseError(f"{path}:{line_number}: duplicate '-- +goose Down' annotation")
                if "\n".join(buffer).strip():
                    raise MigrationParseError(f"{path}:{buffer_line_number}: statement has no terminating ';'")
                buffer = []
                down_statements = []
                current = down_statements
            elif annotation == _STATEMENT_BEGIN:
                if current is None:
                    raise MigrationParseError(f"{path}:{line_number}: '-- +goose StatementBegin' before '-- +goose Up'")
                if in_block:
                    raise MigrationParseError(f"{path}:{line_number}: nested '-- +goose StatementBegin'")
                in_block = True
                block_line_number = line_number
            elif annotation == _STATEMENT_END:
                if current is None or not in_block:
                    raise MigrationParseError(f"{path}:{line_number}: '-- +goose StatementEnd' without '-- +goose StatementBegin'")
                if statement := "\n".join(buffer).strip():
                    current.append(statement)
                buffer = []
                in_block = False
            else:
                use_transaction = False
            continue

        # goose's check, kept exact: only an empty line is skipped here, so a whitespace-only
        # line starts a statement and the comments after it become part of that statement.
        if not buffer and (not line or stripped.startswith("--")):
            continue
        if current is None:
            raise MigrationParseError(f"{path}:{line_number}: SQL before the '-- +goose Up' annotation")
        # A whitespace-only line can open the buffer; errors name the first line with text.
        if stripped and not any(part.strip() for part in buffer):
            buffer_line_number = line_number
        buffer.append(line)
        if not in_block and _ends_statement(line):
            current.append("\n".join(buffer).strip())
            buffer = []

    if current is None:
        raise MigrationParseError(f"{path}: no '-- +goose Up' annotation")
    if in_block:
        raise MigrationParseError(f"{path}:{block_line_number}: '-- +goose StatementBegin' without '-- +goose StatementEnd'")
    if "\n".join(buffer).strip():
        raise MigrationParseError(f"{path}:{buffer_line_number}: statement has no terminating ';'")
    return Migration(
        version=version,
        description=description,
        path=path,
        up_statements=tuple(up_statements),
        down_statements=None if down_statements is None else tuple(down_statements),
        use_transaction=use_transaction,
    )


def collect_migrations(directory: Path) -> list[Migration]:
    """
    Parse every `.sql` file in a directory, ordered by integer version.

    Other files and subdirectories are ignored. Raises `MigrationParseError` when a file
    is malformed or two files share a version.
    """
    paths = sorted(path for path in directory.iterdir() if path.suffix == ".sql" and path.is_file())
    migrations: dict[int, Migration] = {}
    for path in paths:
        migration = parse_migration(path)
        existing = migrations.get(migration.version)
        if existing is not None:
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
    # lone `\r` inside a string literal into `\n`; goose only drops the `\r` of a `\r\n`.
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        line_number = data.count(b"\n", 0, error.start) + 1
        raise MigrationParseError(f"{path}:{line_number}: not valid UTF-8 ({error.reason} at byte {error.start})") from error
    return [line.removesuffix("\r") for line in text.split("\n")]


def _parse_annotation(path: Path, line_number: int, line: str) -> str:
    # goose rejects an indented annotation rather than treating it as a comment.
    if line[:1] in (" ", "\t"):
        raise MigrationParseError(f"{path}:{line_number}: annotation must start at the beginning of the line")
    command = line.replace("--", "").replace("+goose", "", 1)
    if "+goose" in command:
        raise MigrationParseError(f"{path}:{line_number}: more than one '+goose' in annotation")
    command = command.strip()
    for annotation in _UNSUPPORTED_ANNOTATIONS:
        if command.casefold() == annotation.casefold():
            raise MigrationParseError(f"{path}:{line_number}: annotation {annotation!r} is not supported")
    for annotation in _ANNOTATIONS:
        if command.casefold() == annotation.casefold():
            return annotation
    raise MigrationParseError(f"{path}:{line_number}: unknown annotation {command!r}, expected one of {', '.join(_ANNOTATIONS)}")


def _ends_statement(line: str) -> bool:
    # goose's rule: the last whitespace-separated word before one starting with `--`.
    last_word = ""
    for word in line.split():
        if word.startswith("--"):
            break
        last_word = word
    return last_word.endswith(";")
