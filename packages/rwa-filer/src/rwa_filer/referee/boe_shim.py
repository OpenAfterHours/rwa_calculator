"""
Arelle plug-in shim — the stock filing-rule plug-in with its EIOPA date switch off.

Pipeline position:
    runner.run_referee -> worker (``plugins=<this file's path>``) -> Arelle
        loads this file BY PATH, in the worker's process, in place of
        ``validate/EBA``

Why it exists
    ``validate/EBA`` 1.2 (arelle-release 2.47.5) sets ``val.isEIOPA_2_0_1``
    from the ``schemaRef`` date for EBA runs as well as EIOPA ones. Every Bank
    of England entry point is dated after 2015-10-21, so under the ``eba``
    disclosure system the plug-in takes EIOPA branches whose message codes
    (``EIOPA.*``) are then filtered out. That
    - silences EBA.2.7 (unused context), EBA.2.22 (unused unit) and the
      monetary arm of EBA.2.18 (``decimals`` below -3),
    - leaves the currency-of-denomination dimensions of EBA.3.1 uninitialised,
      and
    - raises a false EBA.1.4 for ``encoding="utf-8"`` without a byte-order mark.

Key responsibilities:
- Delegate every hook to the stock plug-in, unchanged.
- After the stock set-up hook, reset the two EIOPA flags and initialise the
  three names the EBA branch of the fact checks reads.

Constraints on this file
- Arelle loads it by file path, as a top-level module, in an environment that
  need not have rwa-filer: standard library only, no relative imports.
- It reaches Arelle through ``importlib.import_module``, on use: nothing here
  imports Arelle statically, so rwa-filer's own environment and type checker
  never need it, and importing this module without Arelle is harmless.
- Arelle reads ``__pluginInfo__`` from this file's SYNTAX TREE before it
  imports it. It must stay a plain assignment of a literal dict, placed after
  the functions it names, and each hook value must be the bare name of a
  function ``def``-ined in this file — which is why the dict is at the bottom.

References:
- Arelle (arelle-release 2.47.5): ``plugin/validate/EBA/__init__.py`` —
  ``validateSetup``; ``plugin_system/_plugin_manager.py`` — ``parsePluginInfo``
- BoE XBRL Filing Manual v1.0.1: 1.4, 2.7, 2.18, 2.22, 3.1
"""

from __future__ import annotations

import importlib
from typing import Any

# =============================================================================
# Constants
# =============================================================================

STOCK_PLUGIN = "arelle.plugin.validate.EBA"
MODEL_VALUE = "arelle.ModelValue"


# =============================================================================
# Main entry point — the hook that differs from the stock plug-in
# =============================================================================


def validate_setup(val: Any, parameters: Any = None, *args: Any, **kwargs: Any) -> None:
    """Run the stock set-up, then undo the EIOPA switch for an EBA-type validation."""
    _stock().validateSetup(val, parameters, *args, **kwargs)
    if not getattr(val, "validateEBA", False):
        return
    val.isEIOPAfullVersion = val.isEIOPA_2_0_1 = False
    qname = importlib.import_module(MODEL_VALUE).qname
    prefixes = val.modelXbrl.modelDocument.xmlRootElement.nsmap
    val.eba_qnDimCUS = qname("eba_dim:CUS", prefixes)
    val.eba_qnDimCCA = qname("eba_dim:CCA", prefixes)
    val.eba_qnCAx1 = qname("eba_CA:x1", prefixes)


# =============================================================================
# Hooks delegated unchanged
# =============================================================================


def disclosure_system_types(disclosure_system: Any, *args: Any, **kwargs: Any) -> Any:
    """The disclosure-system types the stock plug-in registers."""
    return _stock().disclosureSystemTypes(disclosure_system, *args, **kwargs)


def disclosure_system_config_url(disclosure_system: Any, *args: Any, **kwargs: Any) -> Any:
    """The stock plug-in's disclosure-system configuration file."""
    return _stock().disclosureSystemConfigURL(disclosure_system, *args, **kwargs)


def validate_finish(val: Any, *args: Any, **kwargs: Any) -> None:
    """The stock end-of-validation checks (non-streaming)."""
    _stock().validateNonStreamingFinish(val, *args, **kwargs)


def validate_streaming_facts(val: Any, facts_to_check: Any, *args: Any, **kwargs: Any) -> Any:
    """The stock per-batch fact checks (streaming)."""
    return _stock().validateStreamingFacts(val, facts_to_check, *args, **kwargs)


def validate_streaming_finish(val: Any, *args: Any, **kwargs: Any) -> None:
    """The stock end-of-validation checks (streaming)."""
    _stock().validateStreamingFinish(val, *args, **kwargs)


# =============================================================================
# Private helpers
# =============================================================================


def _stock() -> Any:
    """The stock plug-in module; resolved on use, so this file imports without Arelle."""
    return importlib.import_module(STOCK_PLUGIN)


# =============================================================================
# Plug-in declaration — read from the syntax tree; keep it literal and last
# =============================================================================

__pluginInfo__ = {
    "name": "Validate BoE filing rules (validate/EBA, EIOPA date switch off)",
    "version": "0.1",
    "description": (
        "Stock validate/EBA with isEIOPA_2_0_1 forced off for EBA-type disclosure systems."
    ),
    "license": "Apache-2",
    "author": "rwa-filer",
    "copyright": "n/a",
    "DisclosureSystem.Types": disclosure_system_types,
    "DisclosureSystem.ConfigURL": disclosure_system_config_url,
    "Validate.XBRL.Start": validate_setup,
    "Validate.XBRL.Finally": validate_finish,
    "Streaming.ValidateFacts": validate_streaming_facts,
    "Streaming.ValidateFinish": validate_streaming_finish,
}
