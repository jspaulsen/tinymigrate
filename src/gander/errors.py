class GanderError(Exception):
    """
    Base class for every error gander raises.
    """


class MigrationParseError(GanderError):
    """
    A migration file, or a directory of them, that does not follow goose's format.
    """
