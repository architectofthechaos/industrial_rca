"""S2.2 — PI WebID encode/decode.

Real PI WebIDs are opaque server-issued tokens. Here a WebID is a reversible,
URL-safe base64 encoding of the fixture signal key ("<tag>.<role>"), so the
simulator can resolve a WebID back to a signal with no server-side table.
"""
from __future__ import annotations

import base64

_PREFIX = "S1"   # marks our scheme; mirrors PI's "F1..."/"E1..." WebID prefixes


def encode_webid(signal_key: str) -> str:
    raw = base64.urlsafe_b64encode(signal_key.encode("utf-8")).decode("ascii")
    return _PREFIX + raw.rstrip("=")


def decode_webid(webid: str) -> str:
    body = webid[len(_PREFIX):] if webid.startswith(_PREFIX) else webid
    padding = "=" * (-len(body) % 4)
    return base64.urlsafe_b64decode(body + padding).decode("utf-8")


__all__ = ["encode_webid", "decode_webid"]
