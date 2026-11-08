class GanderError(Exception):
    """
    Base class for every error gander raises.
    """


class MigrationParseError(GanderError):
    """
    An error raised when a migration file, or a directory of them, does not follow goose's format.
    """


class MigrationExecutionError(GanderError):
    """
    An error raised when the database rejects a migration's SQL or its version-table update.
    """


class UnsupportedDialectError(GanderError):
    """
    An error raised when the engine is for a database gander does not support.
    """


class MigrationRollbackError(GanderError):
    """
    An error raised when the current version has no migration file, or no Down section, to roll back with.
    """
