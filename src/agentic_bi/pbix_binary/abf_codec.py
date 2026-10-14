"""XPress9 framing of the `DataModel` member (compress / decompress).

The `.pbix` stores its data model as a `DataModel` member: a 102-byte UTF-16LE
signature followed by length-prefixed compressed chunks. Each chunk is
`<uncompressed size:u32><compressed size:u32><body>`, and `body` carries two
engine markers (an offset-20 tag and a CRC-32C over its first 28 bytes).

This module is the single place that knows the framing. `xpress9` is an
optional dependency (`pip install -e ".[binary]"`); importing it is deferred so
the rest of the framework stays stdlib-only.

Public API:
    DataModelCodecError            - raised on malformed framing
    xpress9_available() -> bool
    decompress_datamodel(buf) -> bytes
    compress_datamodel(abf) -> bytes
    crc32c(data) -> int
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Signature of the uncompressed stream, padded to 102 bytes (UTF-16LE).
SIGNATURE = "This backup was created using XPress9 compression."
SIGNATURE_SIZE = 102

# Engine framing constants (verified against real DataModel members).
FIELD_A = 0xEE61D1B9
CRC_FIELD_OFFSET = 28
CHUNK_SIZE = 2 * 1024 * 1024  # chunks must be <= 2 MB (larger crashes the engine)


class DataModelCodecError(ValueError):
    """Raised when a `DataModel` member does not match the expected framing."""


def crc32c(data: bytes) -> int:
    """CRC-32C (Castagnoli, reflected polynomial 0x82F63B78)."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if (crc & 1) else crc >> 1
    return crc ^ 0xFFFFFFFF


def xpress9_available() -> bool:
    """True when the optional `xpress9` codec can be imported."""
    try:
        import xpress9  # noqa: F401
    except ImportError:
        return False
    return True


def _codec():
    try:
        import xpress9
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise DataModelCodecError(
            "the 'xpress9' package is required for DataModel codec operations; "
            'install it with: pip install -e ".[binary]"'
        ) from exc
    return xpress9.Xpress9()


def decompress_datamodel(buf: bytes) -> bytes:
    """Decompress a `DataModel` member into the ABF buffer.

    Args:
        buf: the raw `DataModel` member bytes.

    Returns:
        The decompressed ABF buffer.

    Raises:
        DataModelCodecError: if the member is shorter than the signature or a
            chunk header runs past the end of the buffer.
    """
    if len(buf) < SIGNATURE_SIZE:
        raise DataModelCodecError(
            f"DataModel shorter than the {SIGNATURE_SIZE}-byte signature"
        )
    decoder = _codec()
    offset = SIGNATURE_SIZE
    out = bytearray()
    while offset + 8 <= len(buf):
        uncompressed = int.from_bytes(buf[offset : offset + 4], "little")
        compressed = int.from_bytes(buf[offset + 4 : offset + 8], "little")
        offset += 8
        if offset + compressed > len(buf):
            raise DataModelCodecError(
                "truncated DataModel chunk at offset "
                f"{offset - 8} (need {compressed} bytes)"
            )
        out += decoder.decompress(buf[offset : offset + compressed], uncompressed)
        offset += compressed
    return bytes(out)


def compress_datamodel(abf: bytes) -> bytes:
    """Compress an ABF buffer back into a `DataModel` member.

    The buffer is zero-padded to a 4096-byte boundary first (the engine expects
    page-aligned data), then split into <= 2 MB chunks. Each compressed body
    gets the engine marker at offset 20 and a CRC-32C over its first 28 bytes.
    """
    padded = abf
    remainder = len(abf) % 4096
    if remainder:
        padded = abf + b"\x00" * (4096 - remainder)
    encoder = _codec()
    out = bytearray(SIGNATURE.encode("utf-16le").ljust(SIGNATURE_SIZE, b"\x00"))
    for start in range(0, len(padded), CHUNK_SIZE):
        chunk = padded[start : start + CHUNK_SIZE]
        body = bytearray(encoder.compress(chunk, len(chunk)))
        body[20:24] = FIELD_A.to_bytes(4, "little")
        body[CRC_FIELD_OFFSET : CRC_FIELD_OFFSET + 4] = crc32c(
            bytes(body[0:CRC_FIELD_OFFSET])
        ).to_bytes(4, "little")
        out += len(chunk).to_bytes(4, "little")
        out += len(body).to_bytes(4, "little")
        out += body
    return bytes(out)
