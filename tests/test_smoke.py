import importlib


def test_package_imports_and_exports_version() -> None:
    hm_arch = importlib.import_module("hm_arch")

    assert isinstance(hm_arch.__version__, str)
    assert "__version__" in hm_arch.__all__
