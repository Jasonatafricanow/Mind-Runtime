from importlib.metadata import version

import mind_runtime


def test_package_version_matches_installed_distribution() -> None:
    """Catch a package whose import metadata diverges from its distribution."""
    assert mind_runtime.__version__ == version("mind-runtime")
