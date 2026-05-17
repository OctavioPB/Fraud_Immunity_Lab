"""
Unit tests for the pre-commit synthetic tag enforcement hook.
Validates Hard Rule #3: synthetic data must always carry the tag.
"""

import tempfile
import textwrap
from pathlib import Path

from infra.hooks.check_synthetic_tag import check_file


def _write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(
        suffix="_producer.py", delete=False, mode="w", encoding="utf-8"
    )
    f.write(textwrap.dedent(content))
    f.close()
    return f.name


def test_file_with_synthetic_tag_passes() -> None:
    path = _write_temp("""
        def produce_event():
            payload = {"synthetic": True, "origin": "red_team", "amount": 100}
            kafka.produce(payload)
    """)
    assert check_file(path) is True


def test_file_without_synthetic_tag_fails() -> None:
    path = _write_temp("""
        def produce_event():
            payload = {"amount": 100}
            kafka.produce(payload)
    """)
    assert check_file(path) is False


def test_base_file_is_exempt() -> None:
    f = tempfile.NamedTemporaryFile(
        suffix=".py",
        prefix="base_",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    f.write("def something(): pass")
    f.close()
    assert check_file(f.name) is True
