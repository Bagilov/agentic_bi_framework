"""Unit tests for the ABF codec (XPress9 framing, CRC, round-trip)."""

from __future__ import annotations

import pytest

from agentic_bi.pbix_binary import abf_codec

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")


def test_crc32c_matches_known_vector():
    # The CRC-32C of the ASCII string "123456789" is the standard 0xE3069283.
    assert abf_codec.crc32c(b"123456789") == 0xE3069283


def test_crc32c_of_empty_is_zero():
    assert abf_codec.crc32c(b"") == 0


def test_decompress_rejects_short_signature():
    with pytest.raises(abf_codec.DataModelCodecError, match="signature"):
        abf_codec.decompress_datamodel(b"too short")


def test_decompress_rejects_truncated_chunk():
    header = abf_codec.SIGNATURE.encode("utf-16le").ljust(
        abf_codec.SIGNATURE_SIZE, b"\x00"
    )
    # One chunk header claiming 10 compressed bytes, but no body follows.
    body = (100).to_bytes(4, "little") + (10).to_bytes(4, "little")
    with pytest.raises(abf_codec.DataModelCodecError, match="truncated"):
        abf_codec.decompress_datamodel(header + body)


def test_xpress9_available_reports_true():
    assert abf_codec.xpress9_available() is True


def test_round_trip_preserves_bytes_and_page_aligns():
    payload = bytes(range(256)) * 40  # 10240 B, not page aligned
    framed = abf_codec.compress_datamodel(payload)
    assert (
        framed[: abf_codec.SIGNATURE_SIZE].decode("utf-16le").startswith("This backup")
    )
    restored = abf_codec.decompress_datamodel(framed)
    # The codec pads to a 4096-byte boundary, so the tail is zero padding.
    assert restored[: len(payload)] == payload
    assert len(restored) % 4096 == 0


def test_framing_has_engine_marker_and_crc():
    framed = abf_codec.compress_datamodel(b"\x00" * 8192)
    offset = abf_codec.SIGNATURE_SIZE
    _uncompressed = int.from_bytes(framed[offset : offset + 4], "little")
    compressed = int.from_bytes(framed[offset + 4 : offset + 8], "little")
    body = framed[offset + 8 : offset + 8 + compressed]
    assert int.from_bytes(body[20:24], "little") == abf_codec.FIELD_A
    expected = abf_codec.crc32c(bytes(body[: abf_codec.CRC_FIELD_OFFSET]))
    assert int.from_bytes(body[28:32], "little") == expected
