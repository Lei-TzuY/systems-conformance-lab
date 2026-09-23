from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from email.parser import BytesParser
from email.policy import default

DEFAULT_MAX_MULTIPART_BODY_BYTES = 64 * 1024
MAX_CONFIGURED_MULTIPART_BODY_BYTES = 256 * 1024
MULTIPART_FORM_DATA_BOUNDARY = "systems-conformance-boundary"


def _bounded_nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > MAX_CONFIGURED_MULTIPART_BODY_BYTES:
        raise argparse.ArgumentTypeError(
            "max multipart body bytes must be between 0 and "
            f"{MAX_CONFIGURED_MULTIPART_BODY_BYTES}"
        )
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--max-body-bytes",
        type=_bounded_nonnegative_integer,
        default=DEFAULT_MAX_MULTIPART_BODY_BYTES,
    )
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
    )


def _encode_result(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _read_bounded_input(max_bytes: int) -> bytes | None:
    raw = sys.stdin.buffer.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None
    return raw


def _multipart_message(body: bytes):
    header = (
        "Content-Type: multipart/form-data; boundary=\""
        + MULTIPART_FORM_DATA_BOUNDARY
        + "\"\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("ascii")
    return BytesParser(policy=default).parsebytes(header + body)


def _parse_multipart(body: bytes) -> dict[str, object]:
    try:
        message = _multipart_message(body)
        if not message.is_multipart():
            return {"error": "multipart_parse_error", "ok": False}

        entries: list[dict[str, object]] = []
        for part in message.iter_parts():
            if part.is_multipart():
                return {"error": "multipart_parse_error", "ok": False}
            if part.get_content_disposition() != "form-data":
                return {"error": "multipart_parse_error", "ok": False}

            name = part.get_param("name", header="content-disposition")
            if not isinstance(name, str):
                return {"error": "multipart_parse_error", "ok": False}
            name_hex = name.encode("utf-8").hex()
            filename = part.get_filename()

            if filename is None:
                value = part.get_content()
                if not isinstance(value, str):
                    return {"error": "multipart_parse_error", "ok": False}
                entries.append(
                    {
                        "kind": "text",
                        "name_utf8_hex": name_hex,
                        "value_utf8_hex": value.encode("utf-8").hex(),
                    }
                )
                continue

            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                return {"error": "multipart_parse_error", "ok": False}
            entries.append(
                {
                    "body_hex": payload.hex(),
                    "content_type": part.get_content_type(),
                    "filename_utf8_hex": filename.encode("utf-8").hex(),
                    "kind": "file",
                    "name_utf8_hex": name_hex,
                }
            )
    except (LookupError, TypeError, UnicodeError, ValueError):
        return {"error": "multipart_parse_error", "ok": False}

    return {"entries": entries, "ok": True}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("multipart_form_data_runtime_identity_mismatch\n")
        return 3

    raw = _read_bounded_input(args.max_body_bytes)
    result = (
        {"error": "input_too_large", "ok": False}
        if raw is None
        else _parse_multipart(raw)
    )
    sys.stdout.buffer.write(_encode_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
