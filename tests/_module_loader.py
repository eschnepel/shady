from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "custom_components" / "shady"


def _ensure_package(package_name: str, package_path: Path) -> None:
    if package_name in sys.modules:
        return
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_path)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package


def load_module(module_name: str, relative_path: str):
    module_path = SOURCE_ROOT / relative_path
    parts = module_name.split(".")
    path_parts = list(Path(relative_path).parts[:-1])
    for index, part in enumerate(parts[:-1]):
        package_name = ".".join(parts[: index + 1])
        package_path = SOURCE_ROOT if index == 0 else SOURCE_ROOT.joinpath(*path_parts[:index])
        _ensure_package(package_name, package_path)

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
