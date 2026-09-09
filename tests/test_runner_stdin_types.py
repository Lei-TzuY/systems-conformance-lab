from __future__ import annotations

import sys
from pathlib import Path

import pytest

from systems_conformance import run_process


def python(*args: str) -> list[str]:
    return [sys.executable, "-c", *args]


@pytest.mark.parametrize("invalid_stdin", ["text", bytearray(b"bytes"), memoryview(b"bytes"), None])
def test_rejects_non_bytes_stdin(invalid_stdin: object) -> None:
    with pytest.raises(TypeError, match="stdin must be bytes"):
        run_process(python("pass"), stdin=invalid_stdin)  # type: ignore[arg-type]


def test_invalid_stdin_is_rejected_before_target_executes(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    with pytest.raises(TypeError, match="stdin must be bytes"):
        run_process(
            python(
                "from pathlib import Path; import sys; "
                "Path(sys.argv[1]).write_text('ran')",
                str(marker),
            ),
            stdin="not-bytes",  # type: ignore[arg-type]
        )

    assert not marker.exists()


def test_valid_bytes_stdin_still_reaches_real_child_process() -> None:
    payload = b"binary\x00payload"
    result = run_process(
        python("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
        stdin=payload,
        max_input_bytes=len(payload),
    )

    assert result.exit_code == 0
    assert result.infrastructure_error is None
    assert result.stdout.text == "binary\x00payload"
    assert result.stdout.total_bytes == len(payload)
