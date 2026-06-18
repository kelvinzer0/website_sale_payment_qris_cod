# -*- coding: utf-8 -*-
"""QRIS Dinamis core logic - port dari github.com/verssache/qris-dinamis.

Berisi 4 fungsi pure (no Odoo dependency):
  - calculate_crc16(str) -> str hex 4 char
  - parse_tlv(str) -> list[{tag, length, value}]
  - build_tlv_string(elements) -> str
  - convert_qris(static_qris, amount_str) -> str dynamic_qris
  - validate_qris(qris_str) -> (bool, str)
"""

import logging

_logger = logging.getLogger(__name__)


def calculate_crc16(s: str) -> str:
    """CRC16-CCITT (poly 0x1021, init 0xFFFF). Output 4 hex chars uppercase."""
    crc = 0xFFFF
    for ch in s:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc & 0xFFFF:04X}"


def parse_tlv(data: str):
    """Parse QRIS TLV string jadi list of {tag, length, value}."""
    elements = []
    pos = 0
    while pos < len(data):
        if pos + 4 > len(data):
            break
        tag = data[pos:pos + 2]
        try:
            length = int(data[pos + 2:pos + 4], 10)
        except ValueError:
            break
        if pos + 4 + length > len(data):
            break
        value = data[pos + 4:pos + 4 + length]
        elements.append({"tag": tag, "length": length, "value": value})
        pos += 4 + length
    return elements


def build_tlv_string(elements) -> str:
    """Rebuild TLV string dari list of {tag, value}."""
    parts = []
    for el in elements:
        value = el["value"]
        parts.append(f"{el['tag']}{len(value):02d}{value}")
    return "".join(parts)


def _make_tlv(tag, value):
    return {"tag": tag, "value": str(value)}


def convert_qris(qris_string: str, amount) -> str:
    """Convert QRIS static -> dynamic dengan inject amount.

    amount: str atau numeric, boleh desimal (e.g. "50000.415" atau 50000.415).
    Steps:
      1. Parse TLV
      2. Tag 01 (Point of Init): 11 (static) -> 12 (dynamic)
      3. Skip tags 54, 55, 56, 57, 63 (akan re-insert)
      4. Insert tag 54 = amount sebelum tag 58 (Country Code)
      5. Recalculate CRC16, append "6304" + crc
    """
    amount_str = str(amount)
    elements = parse_tlv(qris_string)
    managed_tags = {"54", "55", "56", "57", "63"}
    result = []
    amount_inserted = False

    for el in elements:
        if el["tag"] in managed_tags:
            continue
        if el["tag"] == "01":
            result.append(_make_tlv("01", "12"))
            continue
        if el["tag"] == "58" and not amount_inserted:
            result.append(_make_tlv("54", amount_str))
            amount_inserted = True
        result.append(el)

    without_crc = build_tlv_string(result)
    crc_input = without_crc + "6304"
    crc = calculate_crc16(crc_input)
    return crc_input + crc


def validate_qris(qris_string: str):
    """Validasi QRIS string. Return (bool, str message).

    Cek struktur minimal dan CRC checksum.
    """
    if not qris_string or len(qris_string) < 8:
        return False, "QRIS string too short or empty"
    # Last 8 chars: "6304" + 4-char CRC value
    if len(qris_string) < 8:
        return False, "QRIS string too short for CRC"
    crc_tag = qris_string[-8:-4]
    if crc_tag != "6304":
        return False, f"Missing CRC tag (6304), got {crc_tag}"
    crc_value = qris_string[-4:]
    crc_input = qris_string[:-4]  # everything before the 4-char CRC value
    expected = calculate_crc16(crc_input)
    if expected != crc_value:
        return False, f"CRC mismatch: expected {expected}, got {crc_value}"
    return True, "Valid"


def format_amount_exact(amount_main: int) -> str:
    """Format exact integer amount jadi string QRIS.

    Flow admin-verifikasi: tidak ada suffix unik, amount = exact order total.
    Contoh: amount_main=50000 -> "50000"
    """
    if amount_main < 0:
        raise ValueError(f"Amount must be >= 0, got {amount_main}")
    return str(int(amount_main))
