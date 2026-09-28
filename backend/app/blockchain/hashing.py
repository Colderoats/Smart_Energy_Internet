"""Canonical JSON + keccak256 fingerprint of an off-chain payload.

Canonical form: keys sorted recursively, no whitespace, UTF-8, no NaN/Infinity.
The Hardhat test suite (blockchain/test/EnergyLedger.test.js) uses the same
form, so a hash computed in JS and here agree for the same payload.
"""

import json
import math
from typing import Any

from eth_utils import keccak


def _clean(value: Any) -> Any:
    """Make a payload JSON-stable before hashing/storing: NaN/inf -> None
    (JSON has no NaN, and JSONB would reject it), tuples -> lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(_clean(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def normalize(payload: Any) -> Any:
    """Round-trip through canonical JSON so the object we store is exactly
    the object we hashed (e.g. tuples become lists, NaN becomes null)."""
    return json.loads(canonical_json(payload))


def payload_hash(payload: Any) -> str:
    return "0x" + keccak(canonical_json(payload).encode("utf-8")).hex()
