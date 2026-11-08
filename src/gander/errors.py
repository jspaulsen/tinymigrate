class GanderError(Exception):
    """
    Base class for every error gander raises.
    """


class MigrationParseError(GanderError):
    """
    An error raised when a migration file, or a directory of them, does not follow goose's format.
    """
