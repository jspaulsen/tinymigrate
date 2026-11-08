import gander
from gander.errors import GanderError


def test_gander_error_is_importable_from_the_package_root() -> None:
    assert gander.GanderError is GanderError


def test_gander_error_is_an_exception() -> None:
    assert issubclass(GanderError, Exception)
