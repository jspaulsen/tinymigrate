import tinymigrate
from tinymigrate.errors import TinymigrateError


def test_tinymigrate_error_is_importable_from_the_package_root() -> None:
    assert tinymigrate.TinymigrateError is TinymigrateError
