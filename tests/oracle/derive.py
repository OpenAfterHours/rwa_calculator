"""
Independent oracle derivations.

This script is the SOLE programmatic source of truth for the expected RWA
values in `expected_values.json`. It uses ONLY Python stdlib (`math`,
`statistics`, `hashlib`, `json`). It DOES NOT IMPORT `rwa_calc`.

Each oracle below corresponds to a section in `ORACLE_DERIVATIONS.md` with the
same identifier (ORC-001, ORC-002, ...). The arithmetic here must produce the
same numbers shown in that document.

Run:
    uv run python tests/oracle/derive.py

Output:
    tests/oracle/expected_values.json
        Embeds a SHA-256 hash of ORACLE_DERIVATIONS.md under
        `derivations_doc_hash`. Line endings are normalised to LF before
        hashing so the hash is stable across Windows / Unix.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).parent
DOC_PATH = HERE / "ORACLE_DERIVATIONS.md"
JSON_PATH = HERE / "expected_values.json"

NORMAL = statistics.NormalDist(0.0, 1.0)


def doc_hash() -> str:
    """SHA-256 of the derivations doc, with line endings normalised to LF.

    The normalisation makes the hash stable across CRLF (Windows) and LF
    (Unix) checkouts.
    """
    raw = DOC_PATH.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


# -----------------------------------------------------------------------------
# ORC-001 -- SA Corporate, unrated
# CRR Art. 122(2): unrated corporate -> 100% RW
# -----------------------------------------------------------------------------
def orc_001() -> dict:
    ead = 1_000_000.0
    risk_weight = 1.00  # CRR Art. 122(2)
    rwa = ead * risk_weight
    return {
        "exposure_id": "ORC-001",
        "framework": "CRR",
        "approach": "SA",
        "exposure_class": "CORPORATE",
        "regulation": "CRR Art. 122(2): unrated corporate -> 100% RW",
        "inputs": {"ead": ead, "cqs": None},
        "expected": {
            "risk_weight": risk_weight,
            "rwa": rwa,
        },
    }


# -----------------------------------------------------------------------------
# ORC-002 -- SA Sovereign, CQS 2 (foreign currency, non-UK)
# CRR Art. 114(2) Table 1: CQS 2 sovereign -> 20% RW.
# Country and currency are non-UK / non-local to avoid the Art. 114(3) UK
# domestic 0% override.
# -----------------------------------------------------------------------------
def orc_002() -> dict:
    ead = 5_000_000.0
    cqs = 2
    risk_weight = 0.20  # CRR Art. 114(2) Table 1, CQS 2
    rwa = ead * risk_weight
    return {
        "exposure_id": "ORC-002",
        "framework": "CRR",
        "approach": "SA",
        "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
        "regulation": "CRR Art. 114(2) Table 1: CQS 2 sovereign (foreign ccy) -> 20% RW",
        "inputs": {
            "ead": ead,
            "cqs": cqs,
            "country_code": "US",
            "currency": "USD",
        },
        "expected": {
            "risk_weight": risk_weight,
            "rwa": rwa,
        },
    }


# -----------------------------------------------------------------------------
# ORC-003 -- F-IRB Corporate, senior unsecured, M = 2.5
# CRR Art. 153(1): IRB risk-weight formula for non-defaulted corporate.
#
#   RW = 12.5 * K
#   K  = LGD * [N((G(PD) + sqrt(R) * G(0.999)) / sqrt(1-R)) - PD] * MA
#   R  = 0.12 * (1 - exp(-50*PD)) / (1 - exp(-50))
#      + 0.24 * (1 - (1 - exp(-50*PD)) / (1 - exp(-50)))
#   b  = (0.11852 - 0.05478 * ln(PD))^2
#   MA = (1 + (M - 2.5) * b) / (1 - 1.5 * b)
# -----------------------------------------------------------------------------
def orc_003() -> dict:
    ead = 10_000_000.0
    pd = 0.01
    lgd = 0.45  # F-IRB senior unsecured supervisory LGD (Art. 161(1)(a))
    m = 2.5

    # Correlation R
    a_factor = (1.0 - math.exp(-50.0 * pd)) / (1.0 - math.exp(-50.0))
    correlation_r = 0.12 * a_factor + 0.24 * (1.0 - a_factor)

    # Maturity adjustment
    b = (0.11852 - 0.05478 * math.log(pd)) ** 2
    maturity_adj = (1.0 + (m - 2.5) * b) / (1.0 - 1.5 * b)

    # Conditional PD
    g_pd = NORMAL.inv_cdf(pd)
    g_999 = NORMAL.inv_cdf(0.999)
    inner = (g_pd + math.sqrt(correlation_r) * g_999) / math.sqrt(1.0 - correlation_r)
    conditional_pd = NORMAL.cdf(inner)

    # Capital and RW (with CRR 1.06 scaling factor; Art. 153(1))
    capital_k = lgd * (conditional_pd - pd) * maturity_adj
    crr_scaling_factor = 1.06
    risk_weight = 12.5 * crr_scaling_factor * capital_k
    rwa = ead * risk_weight

    return {
        "exposure_id": "ORC-003",
        "framework": "CRR",
        "approach": "FIRB",
        "exposure_class": "CORPORATE",
        "regulation": (
            "CRR Art. 153(1): IRB corporate risk-weight formula (includes 1.06 scaling factor)"
        ),
        "inputs": {
            "ead": ead,
            "pd": pd,
            "lgd": lgd,
            "maturity": m,
        },
        "intermediate": {
            "correlation_R": correlation_r,
            "maturity_adj_b": b,
            "maturity_adj_MA": maturity_adj,
            "G_pd": g_pd,
            "G_999": g_999,
            "conditional_pd": conditional_pd,
            "K": capital_k,
            "crr_scaling_factor": crr_scaling_factor,
        },
        "expected": {
            "risk_weight": risk_weight,
            "rwa": rwa,
        },
    }


def main() -> None:
    oracles = [orc_001(), orc_002(), orc_003()]
    payload = {
        "_doc": (
            "Generated by tests/oracle/derive.py. Do NOT hand-edit. "
            "To change values, edit ORACLE_DERIVATIONS.md and derive.py "
            "together, then re-run derive.py."
        ),
        "derivations_doc": "ORACLE_DERIVATIONS.md",
        "derivations_doc_hash_algorithm": "sha256-lf-normalised",
        "derivations_doc_hash": doc_hash(),
        "tolerance_relative": 1e-6,
        "tolerance_absolute_minor": 0.01,
        "oracles": oracles,
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {JSON_PATH.name} with {len(oracles)} oracle exposures.")
    print(f"Derivations doc hash: {payload['derivations_doc_hash']}")


if __name__ == "__main__":
    main()
