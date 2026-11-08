class GanderError(Exception):
    """
    Base class for every error gander raises.
    """


class MigrationParseError(GanderError):
    """
    An error raised when a migration file, or the directory holding them, is missing or does not follow gander's format.
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
    An error raised when there is no migration to roll back, no file for it, or its file has no Down section.
    """


class TransactionStateError(GanderError):
    """
    An error raised when the connection gander is given already has a transaction begun.
    """
