"""
Scope resolver — reporting-entity population filtering.

Pipeline position:
    (loader) -> resolve_scope -> securitisation_allocator -> ...

Key responsibilities:
- Resolve one reporting entity's *membership set* from the reporting-entity
  registry tree: the entity's subtree for a consolidated / sub-consolidated
  submission (mechanically identical — the two differ only in the filing
  label, not the population), the entity alone for an individual submission.
- Attribute every exposure-bearing row to a reporting entity via a
  ``book_code`` -> ``book_entity_mapping`` join, and keep only rows whose
  entity is in the membership set. Rows that cannot be attributed (blank or
  unmapped ``book_code``) are excluded with an ``SCP001`` error.
- Eliminate intragroup exposures on a consolidated / sub-consolidated run
  (``intragroup_entity_reference`` in the membership set); keep them on an
  individual run. On an individual run, when the pack ``intragroup_zero_rw``
  Feature is enabled and both the reporting entity and the tagged intragroup
  entity are in the core UK group (registry ``core_uk_group=True``), set the
  ``intragroup_zero_rw_eligible`` carrier so the SA final-RW override applies
  the CRR Art. 113(6) 0% risk weight. Guarantees whose guarantor is a member
  are internal protection at the consolidated level and are dropped there.
- Accumulate reporting-scope data-quality issues as ``CalculationError``s on
  the bundle (never raise): SCP001 (unattributable book), SCP002 (mapping to
  unknown entity), SCP003 (intragroup tag to unknown entity), SCP004 (invalid
  registry), SCP005 (mixed tagged / untagged counterparty — a WARNING), SCP006
  (requested entity not in the registry).

Only the tiny registry + mapping frames and a couple of tiny diagnostic
aggregates are collected here; every exposure frame stays lazy — the filters
are pure ``LazyFrame.filter`` / semi-join predicates re-sealed to the same raw
edge so downstream stages are untouched.

Known limitation: the SCP005 mixed-tagging WARNING is computed over the lending
frames only (facilities / loans / contingents — which always carry
``counterparty_reference``). CCR netting-set and equity grains differ, so a
counterparty that mixes tagged / untagged exposures purely across those frames
is not cross-checked this wave.

References:
- CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
  consolidated levels of application; consolidation eliminates intragroup
  exposures, solo books include them.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import RAW_TABLE_EDGES, SFT_TABLE_EDGES, seal
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity, ReportingBasis

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawCCRBundle, RawDataBundle, RawSFTBundle
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)

# Reporting-scope data-quality codes (CRR Art. 6 / 11-18). Declared one-per-name
# so tests can assert on ``error.code`` without a module-level string collection
# (arch_check check 6 bans those in engine/**).
SCP_UNATTRIBUTABLE_BOOK = "SCP001"
SCP_MAPPING_UNKNOWN_ENTITY = "SCP002"
SCP_INTRAGROUP_UNKNOWN_ENTITY = "SCP003"
SCP_INVALID_REGISTRY = "SCP004"
SCP_MIXED_TAGGING = "SCP005"
SCP_UNKNOWN_REQUESTED_ENTITY = "SCP006"

_REG_REF = "CRR Art. 6 / 11-18"


# =============================================================================
# Main entry point
# =============================================================================


def resolve_scope(
    bundle: RawDataBundle,
    config: CalculationConfig,
    *,
    intragroup_zero_rw: bool = False,
) -> RawDataBundle:
    """Filter ``bundle`` to the reporting scope named by ``config``.

    ``config.reporting_entity`` is an ``entity_reference`` into the
    reporting-entity registry and ``config.reporting_basis`` its consolidation
    basis (the caller guarantees both are set — the stage adapter no-ops when
    the entity is None). Returns a new bundle whose exposure-bearing frames are
    filtered to the resolved membership set, with any SCP data-quality errors
    appended to ``bundle.errors``.

    When ``intragroup_zero_rw`` is enabled (the pack ``intragroup_zero_rw``
    Feature, passed by the stage adapter) and the run is INDIVIDUAL basis, the
    resolver additionally sets the ``intragroup_zero_rw_eligible`` carrier on
    facility / loan / contingent rows whose ``intragroup_entity_reference``
    names a core-UK-group entity — see :func:`_cug_eligibility` and CRR
    Art. 113(6). On every other run the carrier keeps its injected False default.
    """
    requested = config.reporting_entity
    basis = config.reporting_basis
    drop_intragroup = basis is not ReportingBasis.INDIVIDUAL

    # Only the tiny registry + mapping frames are pulled into Python — the tree
    # walk and book attribution are set operations, not frame transforms. Every
    # exposure frame stays lazy.
    registry_df = _collect_optional(bundle.reporting_entities, "reporting_entities")
    entity_set, children, registry_reason = _analyse_registry(registry_df)

    if registry_reason is not None:
        logger.debug("scope: invalid registry (%s); emptying selection", registry_reason)
        error = _scope_error(
            SCP_INVALID_REGISTRY,
            f"Reporting-entity registry is not a valid single-rooted tree: {registry_reason}. "
            "No reporting scope could be resolved; all exposures excluded.",
        )
        return _with_errors(_empty_selection(bundle), bundle, [error])

    if requested not in entity_set:
        logger.debug("scope: requested entity %r absent from registry; emptying", requested)
        error = _scope_error(
            SCP_UNKNOWN_REQUESTED_ENTITY,
            f"Requested reporting entity '{requested}' is not in the reporting-entity "
            "registry; all exposures excluded.",
        )
        return _with_errors(_empty_selection(bundle), bundle, [error])

    membership = _membership(requested, basis, children)

    mapping_df = _collect_optional(bundle.book_entity_mappings, "book_entity_mappings")
    valid_map, all_mapping_books, unknown_mapping_entities = _analyse_mapping(
        mapping_df, entity_set
    )
    membership_books = frozenset(book for book, ent in valid_map.items() if ent in membership)

    # CRR Art. 113(6): resolve the core-UK-group set for the 0% intragroup RW.
    # None => leave the carrier untouched (Feature off, or not individual basis —
    # the override cannot fire there). A set (possibly EMPTY) => the resolver
    # authoritatively overwrites the carrier on every individual-run lending row,
    # clobbering any user-supplied True (bypass closure).
    cug_eligible = _cug_eligibility(registry_df, requested, basis, enabled=intragroup_zero_rw)

    errors = _diagnose(bundle, entity_set, all_mapping_books, unknown_mapping_entities)

    logger.info(
        "scope resolved: entity=%s basis=%s members=%d books=%d cug=%s issues=%d",
        requested,
        basis.value if basis is not None else None,
        len(membership),
        len(membership_books),
        "off" if cug_eligible is None else len(cug_eligible),
        len(errors),
    )

    filtered = _filter_bundle(
        bundle,
        membership_books,
        membership,
        drop_intragroup=drop_intragroup,
        cug_eligible=cug_eligible,
    )
    return _with_errors(filtered, bundle, errors)


# =============================================================================
# Registry + membership
# =============================================================================


def _analyse_registry(
    registry_df: pl.DataFrame,
) -> tuple[frozenset[str], dict[str, list[str]], str | None]:
    """Resolve the registry into (entity set, children map, invalid reason).

    The reason is None for a valid single-rooted tree, else a short human string
    naming the first structural fault (duplicate key, unknown parent, multiple
    roots, or a cycle / disconnected node).
    """
    refs = registry_df["entity_reference"].to_list()
    entity_set = frozenset(refs)
    if len(refs) != len(entity_set):
        return entity_set, {}, "duplicate entity_reference"

    parents = dict(zip(refs, registry_df["parent_entity_reference"].to_list(), strict=True))
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for entity, parent in parents.items():
        if parent is None:
            roots.append(entity)
            continue
        if parent not in entity_set:
            return entity_set, {}, f"parent '{parent}' of '{entity}' is not a registered entity"
        children.setdefault(parent, []).append(entity)

    if not entity_set:
        return entity_set, children, None  # empty registry — handled as SCP006 upstream
    if len(roots) != 1:
        return entity_set, children, f"expected exactly one root, found {len(roots)}"

    reachable = _descendants(roots[0], children)
    if reachable != entity_set:
        return entity_set, children, "registry contains a cycle or a disconnected entity"
    return entity_set, children, None


def _membership(
    requested: str, basis: ReportingBasis | None, children: dict[str, list[str]]
) -> frozenset[str]:
    """Resolve the membership set for a submission.

    Consolidated and sub-consolidated both take the requested entity's subtree
    (inclusive) — the two differ only in the filing label, not the population.
    Individual takes the entity alone.
    """
    if basis is ReportingBasis.INDIVIDUAL:
        return frozenset({requested})
    return _descendants(requested, children)


def _cug_eligibility(
    registry_df: pl.DataFrame,
    requested: str | None,
    basis: ReportingBasis | None,
    *,
    enabled: bool,
) -> frozenset[str] | None:
    """Resolve the core-UK-group set for the Art. 113(6) 0% intragroup RW.

    Returns ``None`` when the carrier must be left untouched — the pack Feature
    is off, or the run is not individual basis (on a consolidated /
    sub-consolidated run intragroup rows are eliminated before weighting, and the
    SA override does not fire on those runs anyway). Otherwise returns the set of
    registry entities carrying ``core_uk_group=True`` (the valid 0% targets), or
    an **empty** set when the reporting entity is not itself in the core UK group
    — a non-None result signals the caller to overwrite the carrier on EVERY
    lending row (True where the per-row tag test in :func:`_set_cug_eligibility`
    matches, explicit False otherwise). Clobbering False on the only path where
    the override can fire (a scoped individual run) closes the user-loadable
    ``intragroup_zero_rw_eligible`` bypass: an input file cannot smuggle in a
    True that survives to the 0% override.

    Note: ``core_uk_group`` is a single Boolean perimeter, so one dataset can
    model only one core UK group — a firm with two distinct Art. 113(6) groups
    would need a group-identifier column instead (a future refinement; matches
    the pinned Wave-4 design).
    """
    if not enabled or basis is not ReportingBasis.INDIVIDUAL:
        return None
    cug = frozenset(
        ref
        for ref, flag in zip(
            registry_df["entity_reference"].to_list(),
            registry_df["core_uk_group"].to_list(),
            strict=True,
        )
        if flag
    )
    # Condition 2: the reporting entity must itself be in the core UK group.
    # Not a member -> no row is eligible, but STILL return a set (empty) so the
    # resolver authoritatively clears the carrier to False on this individual run.
    if requested not in cug:
        return frozenset()
    return cug


def _descendants(root: str, children: dict[str, list[str]]) -> frozenset[str]:
    """The inclusive subtree rooted at ``root`` (BFS over the children map)."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children.get(node, []))
    return frozenset(seen)


def _analyse_mapping(
    mapping_df: pl.DataFrame, entity_set: frozenset[str]
) -> tuple[dict[str, str], frozenset[str], frozenset[str]]:
    """Resolve the book->entity map into (valid map, all books, unknown entities).

    ``valid map`` covers only mapping rows whose entity is registered; rows to an
    unregistered entity are ignored (their entity is returned separately so the
    caller can raise SCP002). ``all books`` covers every book_code that appears
    in the mapping (valid or not) so a book with only an invalid mapping is not
    also mis-reported as unmapped (SCP001).
    """
    valid_map: dict[str, str] = {}
    all_books: set[str] = set()
    unknown_entities: set[str] = set()
    books = mapping_df["book_code"].to_list()
    entities = mapping_df["reporting_entity_reference"].to_list()
    for book, entity in zip(books, entities, strict=True):
        if book is not None:
            all_books.add(book)
        if entity in entity_set:
            if book is not None:
                valid_map[book] = entity
        elif entity is not None:
            unknown_entities.add(entity)
    return valid_map, frozenset(all_books), frozenset(unknown_entities)


# =============================================================================
# Filtering (all lazy; frames re-sealed to their raw edge)
# =============================================================================


def _filter_bundle(
    bundle: RawDataBundle,
    membership_books: frozenset[str],
    membership: frozenset[str],
    *,
    drop_intragroup: bool,
    cug_eligible: frozenset[str] | None = None,
) -> RawDataBundle:
    """Filter every exposure-bearing frame to the membership set.

    An empty ``membership_books`` empties every booking-filtered frame (the
    SCP004 / SCP006 "no scope resolved" case reuses this path). Reference frames
    (ratings, provisions, collateral, mappings, specialised lending) are never
    filtered — dropped exposures simply stop joining to them.

    ``cug_eligible`` (non-None only on an individual-basis run — where
    ``drop_intragroup`` is False, so the two never interact) is the set of
    core-UK-group entities. When set, facility / loan / contingent rows tagged
    intragroup to one of those entities have ``intragroup_zero_rw_eligible``
    flipped True (CRR Art. 113(6)); every other row keeps False. Equity / CCR /
    SFT frames are deliberately out of scope this wave and are never tagged.
    """
    books = sorted(membership_books)
    members = sorted(membership)
    cug_members = sorted(cug_eligible) if cug_eligible is not None else None

    def _lending(
        frame: pl.LazyFrame | None, field: str, *, tag_cug: bool = False
    ) -> pl.LazyFrame | None:
        if frame is None:
            return None
        filtered = _apply_booking(frame, books)
        if drop_intragroup:
            filtered = _drop_intragroup(filtered, members)
        if tag_cug and cug_members is not None:
            filtered = _set_cug_eligibility(filtered, cug_members)
        return seal(filtered, RAW_TABLE_EDGES[field])

    return replace(
        bundle,
        facilities=_lending(bundle.facilities, "facilities", tag_cug=True),
        loans=_lending(bundle.loans, "loans", tag_cug=True),
        contingents=_lending(bundle.contingents, "contingents", tag_cug=True),
        equity_exposures=_lending(bundle.equity_exposures, "equity_exposures"),
        guarantees=_filter_guarantees(bundle.guarantees, members, drop_intragroup=drop_intragroup),
        ccr=_filter_ccr(bundle.ccr, books, members, drop_intragroup=drop_intragroup),
        sft=_filter_sft(bundle.sft, books, members, drop_intragroup=drop_intragroup),
    )


def _apply_booking(frame: pl.LazyFrame, books: list[str]) -> pl.LazyFrame:
    """Keep only rows whose ``book_code`` maps to an in-scope entity."""
    keep = pl.col("book_code").is_in(books) if books else pl.lit(value=False)
    return frame.filter(keep)


def _drop_intragroup(frame: pl.LazyFrame, members: list[str]) -> pl.LazyFrame:
    """Drop rows whose ``intragroup_entity_reference`` is a membership entity."""
    tag = pl.col("intragroup_entity_reference")
    return frame.filter(tag.is_null() | ~tag.is_in(members))


def _set_cug_eligibility(frame: pl.LazyFrame, cug_members: list[str]) -> pl.LazyFrame:
    """Authoritatively (re)set ``intragroup_zero_rw_eligible`` on every lending row.

    CRR Art. 113(6): a row qualifies for the 0% intragroup risk weight when its
    ``intragroup_entity_reference`` names a registry entity with
    ``core_uk_group=True`` (``cug_members``). This OVERWRITES the column on every
    row — True where the tag matches, explicit False otherwise (external rows,
    non-CUG tags, and any user-supplied value) — so the resolver, not the input
    file, is the source of truth on an individual run. An empty ``cug_members``
    (the reporting entity is not itself in the core UK group) clears every row to
    False. Called only on an individual-basis run.
    """
    tag = pl.col("intragroup_entity_reference")
    eligible = (tag.is_not_null() & tag.is_in(cug_members)) if cug_members else pl.lit(value=False)
    return frame.with_columns(eligible.alias("intragroup_zero_rw_eligible"))


def _filter_guarantees(
    guarantees: pl.LazyFrame | None, members: list[str], *, drop_intragroup: bool
) -> pl.LazyFrame | None:
    """Drop guarantees whose guarantor is a membership entity (consolidated only).

    Internal credit protection is not CRM at the consolidated / sub-consolidated
    level; on an individual run the guarantee is kept. Guarantees carry no
    ``book_code`` — they are protection, filtered solely by guarantor membership.
    """
    if guarantees is None or not drop_intragroup:
        return guarantees
    guarantor = pl.col("guarantor_entity_reference")
    filtered = guarantees.filter(guarantor.is_null() | ~guarantor.is_in(members))
    return seal(filtered, RAW_TABLE_EDGES["guarantees"])


def _filter_ccr(
    ccr: RawCCRBundle | None,
    books: list[str],
    members: list[str],
    *,
    drop_intragroup: bool,
) -> RawCCRBundle | None:
    """Filter the nested CCR bundle at netting-set grain.

    Netting sets are booking-filtered (and intragroup-eliminated on a
    consolidated run); surviving netting sets then keep their trades and
    netting-set-keyed collateral via a semi-join. Margin agreements are keyed
    by CSA, not netting set, so an orphaned CSA is left in place (inert — it
    joins to nothing downstream). CCR leaf frames are not brand-validated, so no
    re-seal is required.
    """
    if ccr is None:
        return ccr
    netting_sets = _apply_booking(ccr.netting_sets.netting_sets, books)
    if drop_intragroup:
        netting_sets = _drop_intragroup(netting_sets, members)
    surviving = netting_sets.select("netting_set_id")
    trades = ccr.trades.trades.join(surviving, on="netting_set_id", how="semi")
    collateral = ccr.ccr_collateral.ccr_collateral.join(surviving, on="netting_set_id", how="semi")
    return replace(
        ccr,
        netting_sets=replace(ccr.netting_sets, netting_sets=netting_sets),
        trades=replace(ccr.trades, trades=trades),
        ccr_collateral=replace(ccr.ccr_collateral, ccr_collateral=collateral),
    )


def _filter_sft(
    sft: RawSFTBundle | None,
    books: list[str],
    members: list[str],
    *,
    drop_intragroup: bool,
) -> RawSFTBundle | None:
    """Filter the nested SFT bundle: trades by booking, collateral by semi-join.

    SFT trades denormalise the single-counterparty netting set, so the booking
    filter runs at trade grain; surviving trades keep their netting-set-keyed
    collateral via a semi-join. Both SFT leaf frames are brand-validated, so
    they are re-sealed to their ``raw_sft_*`` edges after filtering.
    """
    if sft is None:
        return sft
    trades = _apply_booking(sft.trades.sft_trades, books)
    if drop_intragroup:
        trades = _drop_intragroup(trades, members)
    new_trades = replace(sft.trades, sft_trades=seal(trades, SFT_TABLE_EDGES["sft_trades"]))

    new_collateral = sft.collateral
    if sft.collateral is not None:
        surviving = trades.select("netting_set_id")
        collateral = sft.collateral.sft_collateral.join(surviving, on="netting_set_id", how="semi")
        new_collateral = replace(
            sft.collateral, sft_collateral=seal(collateral, SFT_TABLE_EDGES["sft_collateral"])
        )
    return replace(sft, trades=new_trades, collateral=new_collateral)


def _empty_selection(bundle: RawDataBundle) -> RawDataBundle:
    """Empty every exposure-bearing frame (the SCP004 / SCP006 loud-fail path)."""
    return _filter_bundle(bundle, frozenset(), frozenset(), drop_intragroup=False)


# =============================================================================
# Diagnostics (SCP001 / SCP002 / SCP003 / SCP005)
# =============================================================================


def _diagnose(
    bundle: RawDataBundle,
    entity_set: frozenset[str],
    all_mapping_books: frozenset[str],
    unknown_mapping_entities: frozenset[str],
) -> list[CalculationError]:
    """Accumulate the reporting-scope data-quality errors for a resolved run.

    Every signal is derived from tiny aggregates (distinct book / tag pairs and
    per-counterparty tag consistency) collected off the exposure frames — the
    frames themselves are never materialised, and the republished frames stay
    lazy.
    """
    errors: list[CalculationError] = []

    if unknown_mapping_entities:
        errors.append(
            _scope_error(
                SCP_MAPPING_UNKNOWN_ENTITY,
                "Book-to-entity mapping references reporting entities absent from the "
                f"registry: {_fmt(unknown_mapping_entities)}; those mapping rows are ignored.",
            )
        )

    book_tag_frames = _book_tag_projections(bundle)
    if book_tag_frames:
        pairs = pl.concat(book_tag_frames, how="vertical").unique().collect()
        unattributable = _unattributable_books(pairs, all_mapping_books)
        if unattributable:
            errors.append(
                _scope_error(
                    SCP_UNATTRIBUTABLE_BOOK,
                    "Exposures carry a blank or unmapped book_code and cannot be attributed "
                    f"to a reporting entity: {_fmt(unattributable)}; those rows are excluded.",
                )
            )
        unknown_tags = _unknown_tags(pairs, entity_set)
        if unknown_tags:
            errors.append(
                _scope_error(
                    SCP_INTRAGROUP_UNKNOWN_ENTITY,
                    "Exposures are tagged intragroup to entities absent from the registry: "
                    f"{_fmt(unknown_tags)}; those rows are kept and treated as external.",
                )
            )

    mixed = _mixed_tagging_counterparties(bundle)
    if mixed:
        errors.append(
            _scope_error(
                SCP_MIXED_TAGGING,
                "Counterparties carry a mix of intragroup-tagged and untagged exposures "
                f"(inconsistent tagging): {_fmt(mixed)}.",
                severity=ErrorSeverity.WARNING,
            )
        )
    return errors


def _book_tag_projections(bundle: RawDataBundle) -> list[pl.LazyFrame]:
    """Narrow (book_code, intragroup) projections of every exposure frame.

    Every exposure-bearing frame carries both columns after the loader seal
    (facility / loan / contingent / equity schemas plus the CCR netting-set and
    SFT trade schemas), so the projections union cleanly for one diagnostic
    collect.
    """
    frames = [
        bundle.facilities,
        bundle.loans,
        bundle.contingents,
        bundle.equity_exposures,
    ]
    if bundle.ccr is not None:
        frames.append(bundle.ccr.netting_sets.netting_sets)
    if bundle.sft is not None:
        frames.append(bundle.sft.trades.sft_trades)
    return [
        frame.select("book_code", "intragroup_entity_reference")
        for frame in frames
        if frame is not None
    ]


def _unattributable_books(pairs: pl.DataFrame, all_mapping_books: frozenset[str]) -> list[str]:
    """Distinct book_codes that are blank, or that no mapping row attributes."""
    offenders: set[str] = set()
    for book in pairs["book_code"].to_list():
        if book is None or book == "":
            offenders.add("<blank>")
        elif book not in all_mapping_books:
            offenders.add(book)
    return sorted(offenders)


def _unknown_tags(pairs: pl.DataFrame, entity_set: frozenset[str]) -> list[str]:
    """Distinct intragroup tags that name an entity absent from the registry."""
    return sorted(
        tag
        for tag in set(pairs["intragroup_entity_reference"].to_list())
        if tag is not None and tag not in entity_set
    )


def _mixed_tagging_counterparties(bundle: RawDataBundle) -> list[str]:
    """Counterparties with both intragroup-tagged and untagged lending exposures.

    Computed over the lending frames (facilities / loans / contingents), which
    always carry ``counterparty_reference``. A tiny per-counterparty aggregate is
    collected — the frames stay lazy.
    """
    frames = [
        frame.select("counterparty_reference", "intragroup_entity_reference")
        for frame in (bundle.facilities, bundle.loans, bundle.contingents)
        if frame is not None
    ]
    if not frames:
        return []
    tagged = pl.col("intragroup_entity_reference").is_not_null()
    mixed = (
        pl.concat(frames, how="vertical")
        .group_by("counterparty_reference")
        .agg(tagged.any().alias("has_tagged"), (~tagged).any().alias("has_untagged"))
        .filter(pl.col("has_tagged") & pl.col("has_untagged"))
        .select("counterparty_reference")
        .collect()
    )
    return sorted(cp for cp in mixed["counterparty_reference"].to_list() if cp is not None)


# =============================================================================
# Private helpers
# =============================================================================


def _collect_optional(frame: pl.LazyFrame | None, field: str) -> pl.DataFrame:
    """Collect an optional registry / mapping frame, or a schema-complete stand-in.

    These two frames are tiny (one row per legal entity / booking book), so
    pulling them into Python for the tree walk and book attribution is cheap —
    unlike the exposure frames, which stay lazy. When the frame is absent an
    empty frame carrying the raw-edge schema is used, so column access is safe.
    """
    source = frame if frame is not None else RAW_TABLE_EDGES[field].empty_frame()
    return source.collect()


def _with_errors(
    filtered: RawDataBundle, original: RawDataBundle, errors: list[CalculationError]
) -> RawDataBundle:
    """Append scope errors to the bundle's error list (preserving load errors)."""
    if not errors:
        return filtered
    return replace(filtered, errors=[*original.errors, *errors])


def _scope_error(
    code: str, message: str, severity: ErrorSeverity = ErrorSeverity.ERROR
) -> CalculationError:
    """Build a reporting-scope ``CalculationError`` (never raised — accumulated)."""
    return CalculationError(
        code=code,
        message=message,
        severity=severity,
        category=ErrorCategory.SCOPE,
        regulatory_reference=_REG_REF,
    )


def _fmt(values: frozenset[str] | list[str]) -> str:
    """Render a small set of references for an error message (sorted, capped)."""
    ordered = sorted(values)
    shown = ordered[:10]
    suffix = f" (+{len(ordered) - len(shown)} more)" if len(ordered) > len(shown) else ""
    return ", ".join(shown) + suffix
