"""Minimal EPUB built in memory, reusing the story-core test factory."""

import importlib.util
from pathlib import Path

_FACTORY = Path(__file__).resolve().parents[3] / "packages" / "story-core" / "tests" / "epub_factory.py"
_spec = importlib.util.spec_from_file_location("story_core_epub_factory", _FACTORY)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

SAMPLE_EPUB: bytes = _module.build_epub(_module.SAMPLE_EPUB_DOCS)
