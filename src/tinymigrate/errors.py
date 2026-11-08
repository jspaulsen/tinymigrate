class TinymigrateError(Exception):
    """
    Base class for every error tinymigrate raises.
    """


class MigrationParseError(TinymigrateError):
    """
    An error raised when a migration file, or the directory holding them, is missing or does not follow tinymigrate's format.
    """


class MigrationExecutionError(TinymigrateError):
    """
    An error raised when the database rejects a migration's SQL or its version-table update.
    """


class UnsupportedDialectError(TinymigrateError):
    """
    An error raised when the engine is for a database tinymigrate does not support.
    """


class MigrationRollbackError(TinymigrateError):
    """
    An error raised when there is no migration to roll back, no file for it, or its file has no Down section.
    """


class TransactionStateError(TinymigrateError):
    """
    An error raised when the connection tinymigrate is given already has a transaction begun.
    """
