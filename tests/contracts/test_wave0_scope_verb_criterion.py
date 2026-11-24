"""
Wave 0 scope-sentence / operative-verb gate (plan item P5.78).

The escaped defect: the Basel 3.1 equity transitional (PRA Credit Risk:
General Provisions rules 4.1-4.3) was coded as a ``max_horizontal`` floor that
never bound, and the plan audit that should have caught it read the code as the
rule. P1.296's audit described rules 4.2 / 4.3 by the code's floor, cited the
code line, and recorded the bullet's correct claim about the 2027 weight as
WRONG — inside an audit whose verdict otherwise *confirmed* the diagnosis. It
never quoted rule 4.1 (the scope sentence: firms *without* IRB permission) or
rule 4.2's verb ("shall be assigned"). Escape log 2026-11-16, LESSONS A1.

The gate this pins is the ``wrong-premise`` prescription ("strengthen Wave 0"):

- ``premise-auditor.md`` states the criterion, with both triggers and on any
  verdict. Its body asks for verbatim, page-cited quotes of the scope sentence,
  of every modifying provision and of the operative verb, and for a one-line
  verb-versus-mechanism comparison; it treats a floor or max against "shall be
  assigned" as a finding; and its output format declares a mandatory section
  with a field for each;
- ``next-items.md`` Step 4d's Wave 0 block holds a ``C0.n`` that names that
  section. The section title is read from the auditor's own output format, not
  typed here. The quote requirements of the auditor's body and of the ``C0.n``
  are asserted on their text with the section's name (and the ``C0.n``'s own
  title sentence) stripped, so a criterion that keeps only the name cannot pass;
- each of the three fail lists — the auditor's "It fails" sentence, the
  ``C0.n``'s ``revise`` sentence and ``/implement-scenario`` Step 0's re-invoke
  sentence — names all five elements, the modifying-provisions line included;
- no site is gated on a ``PREMISE`` verdict token (the ``C0.n``, the auditor's
  criterion, its output placeholder, Step 0's paragraph). A trigger keyed on
  ``refuted`` would have missed P1.296. The verdict tokens are read from the
  auditor's ``PREMISE:`` line;
- trigger (b)'s exception stays confined to question 2's citation of the code;
- ``next-items.md`` sends every verdict to the Wave 0 reviewer before an item
  stops: Step 3a's branches, and its stop sentence conditioned on ``pass`` alone;
  the state table's ``pass`` row defers a refutation to Step 3a instead of
  advancing it; and Step 7 closes a refuted bullet only on the drop reason Step
  3a sets after a passed review, leaving open the bullet of a refutation the
  table dropped;
- ``/implement-scenario`` Step 0, which has no Wave 0 reviewer, makes the
  orchestrator apply the same criterion, a refutation expressly included;
- each detector here is shown to fire on the repo's own sibling shape (C0.5 and
  the Corrected-premise placeholder are verdict-gated; the verbatim-quote
  criterion that P1.296 passed names neither trigger), so none is a guard that
  is green in both states (LESSONS C11/C12).

These are text detectors. They see the shapes named above, not every way the
criterion could be weakened in prose. This is a presence-and-wiring test: it
proves the gate is wired, not that an agent follows it — the reviewer applying
the criterion checks that the quote is there, cited and compared with the code,
not that it is true.

References:
- docs/development/escape-log.md — 2026-11-16 equity-transitional entry
- .claude/LESSONS.md A1 — a reading that agrees with the code may have read the code
- .claude/commands/next-items.md Step 7.5 — a reviewer criterion is graduation form 4
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PREMISE_AUDITOR = REPO_ROOT / ".claude" / "agents" / "premise-auditor.md"
NEXT_ITEMS = REPO_ROOT / ".claude" / "commands" / "next-items.md"
IMPLEMENT_SCENARIO = REPO_ROOT / ".claude" / "commands" / "implement-scenario.md"

#: The two halves of the criterion the escape log prescribes. Matching is on
#: whitespace-normalised, lower-cased text so a line wrap cannot hide either.
_SCOPE_PHRASE = "scope sentence"
_VERB_PHRASE = "operative verb"

#: Trigger (a): the audit narrows a bullet claim (P1.296 rejected one sub-claim
#: of a diagnosis it confirmed) to a reading that is what the code already does.
#: Keyed on "narrow", not "reject": a criterion that merely retells P1.296
#: ("rejected one claim") must not satisfy it.
_TRIGGER_A = re.compile(r"\bnarrow\w*\b.*\bwhat the code\b", re.DOTALL)
#: Trigger (b): the audit cites a source line as evidence of what a rule does.
_TRIGGER_B = re.compile(r"file:line")
#: A sentence that carves a citation out of trigger (b) ("... is not (b)").
_TRIGGER_B_EXCEPTION = re.compile(r"\b(?:not|never)\s+\(b\)")

#: The verb P1.296 replaced with the code's floor.
_ASSIGN_VERB = "shall be assigned"

#: The five things whose absence fails a triggered audit, as each fail list must
#: name them (hyphens read as spaces, so "scope-sentence quote" matches).
_FAIL_ELEMENTS: dict[str, re.Pattern[str]] = {
    "scope-sentence quote": re.compile(r"\bscope sentence quote\b"),
    "page index": re.compile(r"\bpage index\b"),
    "modifying-provisions line": re.compile(r"\bmodifying provisions? line\b"),
    "verb quote": re.compile(r"\bverb quote\b"),
    "mechanism line": re.compile(r"\bmechanism (?:(?:vs|versus) verb )?line\b"),
}


def test_auditor_output_format_declares_the_scope_and_verb_section() -> None:
    """The auditor's output carries one mandatory section for the scope sentence and verb."""
    # Arrange
    title = _scope_section_title()

    # Act
    placeholder = _norm(_scope_placeholder())

    # Assert
    assert "not triggered" in placeholder, (
        f"the '## {title}' placeholder gives no 'not triggered' form — the section must be "
        "present on every audit so a missing one is visibly missing, not silently optional."
    )
    for required in ("page index", "mechanism", "modif"):
        assert required in placeholder, (
            f"the '## {title}' placeholder does not ask for '{required}': a triggered section "
            "must cite the PDF page, compare the code's mechanism with the verb, and quote "
            "any provision that modifies the rule."
        )


def test_auditor_output_placeholder_asks_for_verbatim_scope_and_verb_quotes() -> None:
    """The placeholder has its own field for each quote — not only the section's name."""
    # Arrange
    fields = _placeholder_fields(_scope_placeholder())

    # Act
    scope = fields.get(_SCOPE_PHRASE, "")
    verb = fields.get(_VERB_PHRASE, "")
    modifying = next((text for label, text in fields.items() if label.startswith("modif")), "")

    # Assert
    assert "verbatim" in scope and "page index" in scope, (
        f"the placeholder has no '- Scope sentence:' field asking for a verbatim, page-cited "
        f"quote (fields: {sorted(fields)}). P1.296 never quoted rule 4.1; a section whose "
        "only mention of the scope sentence is its title does not ask for one."
    )
    assert "verbatim" in verb, (
        f"the placeholder has no '- Operative verb:' field asking for a verbatim quote "
        f"(fields: {sorted(fields)})."
    )
    assert all(part in modifying for part in ("verbatim", "page index", "none found")), (
        f"the placeholder has no '- Modifying provisions:' field asking for a verbatim, "
        f"page-cited quote or 'none found: <where looked>' (fields: {sorted(fields)})."
    )


def test_auditor_states_the_criterion_on_any_verdict_with_both_triggers() -> None:
    """The criterion fires on any verdict, on a code-agreeing narrowing or a cited code line."""
    # Arrange
    body = _auditor_criterion()

    # Act
    text = _norm(body)

    # Assert
    assert "any verdict" in text, (
        "the criterion does not say it fires on any verdict; P1.296 rejected a sub-claim "
        "inside a confirmed diagnosis, so a refuted-only trigger would not have fired."
    )
    assert _TRIGGER_A.search(text), "trigger (a) — a claim rejected or narrowed toward the code"
    assert _TRIGGER_B.search(text), "trigger (b) — a file:line cited as evidence of a rule"


def test_auditor_criterion_requires_verbatim_scope_and_verb_quotes() -> None:
    """With headings and the section's name stripped, the body still demands every quote."""
    # Arrange
    paragraphs = _paragraphs(_strip_name(_auditor_criterion()))
    lead = [
        i
        for i, p in enumerate(paragraphs)
        if "quote verbatim" in _norm(p) and "page index" in _norm(p)
    ]
    assert len(lead) == 1, (
        f"{len(lead)} paragraphs of the criterion lead into a verbatim, page-cited quote list "
        "(expected 1) — the criterion no longer says what must be quoted."
    )

    # Act
    items = [_norm(p) for p in _list_after(paragraphs, lead[0])]
    unit = " ".join([_norm(paragraphs[lead[0]]), *items])

    # Assert
    assert _SCOPE_PHRASE in unit, (
        "the auditor's verbatim-quote list does not include the scope sentence — the very "
        "quote P1.296 never made (rule 4.1)."
    )
    assert _VERB_PHRASE in unit, "the auditor's verbatim-quote list omits the operative verb"
    assert any("modif" in item for item in items), (
        "the auditor's verbatim-quote list has no item for a provision that modifies the "
        "controlling one — the rule in another Part that ORC-080's quote of the article missed."
    )


def test_auditor_criterion_asks_for_the_verb_versus_mechanism_line() -> None:
    """Outside its fail list, the auditor's body asks whether the code's mechanism matches."""
    # Arrange
    sentences = _sentences(_strip_name(_auditor_criterion()))

    # Act
    asking = [
        s
        for s in sentences
        if "mechanism" in s and "verb" in s and "match" in s and not s.startswith("it fails")
    ]

    # Assert
    assert asking, (
        "the auditor's criterion never asks whether the code's mechanism (floor, max, cap, "
        "...) matches the operative verb; only its fail list names that line."
    )


def test_auditor_criterion_treats_a_floor_against_shall_be_assigned_as_a_finding() -> None:
    """A floor or max where the rule says "shall be assigned" is a finding, not a confirmation."""
    # Arrange
    sentences = _sentences(_strip_name(_auditor_criterion()))

    # Act
    stating = [s for s in sentences if _is_floor_finding(s)]

    # Assert
    assert stating, (
        f"the criterion never says that a floor or max against '{_ASSIGN_VERB}' is a finding. "
        "That is the reading P1.296 inverted; without it the verb-versus-mechanism line has "
        "no rule to apply."
    )


@pytest.mark.parametrize("site", ["auditor criterion", "C0.9 revise", "implement-scenario Step 0"])
def test_every_fail_list_names_all_five_elements(site: str) -> None:
    """Each list of what fails a triggered audit names every element, modifying provisions too."""
    # Arrange
    sentence = _FAIL_SENTENCES[site]()

    # Act
    text = sentence.replace("-", " ")
    missing = sorted(name for name, pattern in _FAIL_ELEMENTS.items() if not pattern.search(text))

    # Assert
    assert not missing, (
        f"the {site} fail list omits {missing}: {sentence!r}. An audit that quotes only the "
        "article it treats as controlling can match scope and verb to the code and never "
        "reach the rule in another Part that modifies it."
    )


def test_wave0_review_criteria_name_the_auditor_section() -> None:
    """Exactly one Wave 0 reviewer criterion checks the auditor's scope-and-verb section."""
    # Arrange
    title = _norm(_scope_section_title())

    # Act
    naming = [cid for cid, body in _wave0_criteria().items() if title in _norm(body)]

    # Assert
    assert len(naming) == 1, (
        f"{len(naming)} Wave 0 criteria in next-items.md Step 4d name the auditor's "
        f"'{title}' section (expected 1). The reviewer applies only the criteria it is "
        "given, so a check written anywhere else never fires on Wave 0."
    )


def test_wave0_scope_criterion_requires_the_quotes_not_only_the_section() -> None:
    """The reviewer check, title and section name stripped, still demands every quote."""
    # Arrange
    cid, body = _scope_criterion()

    # Act
    sentences = _sentences(_strip_name(_strip_title(" ".join(body.split()))))
    asks = [s for s in sentences if s.startswith("when triggered")]
    assert asks, f"{cid} has no 'When triggered, ...' sentence saying what the section holds"
    scope_quote = [
        s
        for s in asks
        if "quot" in s and _SCOPE_PHRASE in s and "verbatim" in s and "page index" in s
    ]
    verb_quote = [s for s in asks if "quot" in s and _VERB_PHRASE in s]
    modifying_quote = [s for s in asks if "quot" in s and "modif" in s]
    mechanism = [s for s in asks if "mechanism" in s and "verb" in s]
    floor_finding = [s for s in sentences if _is_floor_finding(s) and "`revise`" in s]

    # Assert
    assert scope_quote, f"{cid} does not require the scope sentence quoted verbatim with page index"
    assert verb_quote, f"{cid} does not require the operative verb quoted"
    assert modifying_quote, f"{cid} does not require any modifying provision quoted"
    assert mechanism, f"{cid} does not ask for the code-mechanism-vs-verb comparison"
    assert floor_finding, (
        f"{cid} does not `revise` a 'match' that pairs a floor or max with '{_ASSIGN_VERB}'"
    )


@pytest.mark.parametrize(
    "site",
    ["C0.9", "auditor criterion", "auditor output placeholder", "implement-scenario Step 0"],
)
def test_no_site_gates_the_criterion_on_a_verdict(site: str) -> None:
    """No statement of the criterion opens it on `refuted` / `rescoped` alone."""
    # Arrange
    tokens = _verdict_tokens()
    text = _GATE_SITES[site]()

    # Act
    gate = _verdict_gate(text, tokens)

    # Assert
    assert gate is None, (
        f"the {site} is gated on a PREMISE verdict token ({gate!r}). The trigger is the "
        "code-agreeing reading, on any verdict: P1.296 was a confirmed diagnosis."
    )


def test_wave0_scope_criterion_says_it_applies_on_any_verdict() -> None:
    """The reviewer check says in terms that it runs whatever the verdict."""
    # Arrange
    cid, body = _scope_criterion()

    # Act
    text = _norm(body)

    # Assert
    assert "any verdict" in text, f"{cid} does not say it applies on any verdict"


def test_verdict_gating_detector_fires_on_the_repos_own_gated_shapes() -> None:
    """The gating detector is not green in both states: it flags C0.5 and its placeholder."""
    # Arrange
    tokens = _verdict_tokens()
    corrected_premise = [
        body for body in _wave0_criteria().values() if "corrected premise" in _norm(body)
    ]
    assert corrected_premise, "no Wave 0 criterion checks the Corrected premise section"
    shapes = {
        "C0.5 (Corrected premise criterion)": corrected_premise[0],
        "Corrected premise placeholder": _output_placeholder(_corrected_premise_title()),
    }

    # Act
    missed = sorted(name for name, text in shapes.items() if _verdict_gate(text, tokens) is None)

    # Assert
    assert not missed, (
        f"the verdict-gating detector misses {missed}, which open on `refuted` / `rescoped` — "
        "a detector that cannot see the sibling shape cannot guard against a copy of it."
    )


def test_verdict_gating_detector_sees_paraphrased_gates() -> None:
    """Everyday gate wordings, behind a title sentence or not, are each flagged."""
    # Arrange
    tokens = _verdict_tokens()
    title = f"{_scope_section_title().upper()}."
    corrected_premise = [b for b in _wave0_criteria().values() if "corrected premise" in _norm(b)]
    assert corrected_premise, "no Wave 0 criterion checks the Corrected premise section"
    shapes = {"title + C0.5 gate": f"{title} {corrected_premise[0]}"}
    for token in tokens:
        shapes |= {
            f"only `{token}`": f"{title} Applies only when the verdict is `{token}`.",
            f"when the verdict is `{token}`": (
                f"{title} It is checked when the verdict is `{token}`, and is TRIGGERED when "
                "the audit cites a file:line."
            ),
            f"if the verdict is `{token}`": (
                f"{title} If the verdict is `{token}`, it is TRIGGERED when the audit (a) ..."
            ),
            f"triggered on a `{token}` verdict": (
                f"The section is present on any verdict, but it is triggered on a `{token}` "
                "verdict, whenever either holds:"
            ),
            f"`{token}` only": f'<`{token}` only. Either "not triggered" or ...>',
        }

    # Act
    missed = sorted(name for name, text in shapes.items() if _verdict_gate(text, tokens) is None)

    # Assert
    assert not missed, (
        f"the verdict-gating detector misses {missed}: each restricts the criterion to a "
        "PREMISE verdict, the gate hazard (3) of the P5.78 audit warns about."
    )


def test_wave0_scope_criterion_names_both_triggers_and_the_page_cite() -> None:
    """The reviewer check names both triggers; the quote criterion P1.296 passed names neither."""
    # Arrange
    cid, body = _scope_criterion()
    quote_criteria = {
        other: other_body
        for other, other_body in _wave0_criteria().items()
        if "verbatim regulatory text" in _norm(other_body)
    }
    assert quote_criteria, "no Wave 0 criterion checks the Verbatim regulatory text section"

    # Act
    text = _norm(body)
    controls = {
        other: bool(_TRIGGER_A.search(_norm(b)) or _TRIGGER_B.search(_norm(b)))
        for other, b in quote_criteria.items()
        if other != cid
    }

    # Assert
    assert _TRIGGER_A.search(text), f"{cid} omits trigger (a): a claim narrowed toward the code"
    assert _TRIGGER_B.search(text), f"{cid} omits trigger (b): a cited file:line"
    for required in ("page index", "not triggered", "mechanism"):
        assert required in text, f"{cid} does not check '{required}'"
    assert controls and not any(controls.values()), (
        f"the trigger detectors fire on the verbatim-quote criterion {sorted(controls)}, "
        "so they cannot tell the new check from the one P1.296 already passed."
    )


@pytest.mark.parametrize("site", ["auditor criterion", "C0.9"])
def test_trigger_b_exception_is_confined_to_question_2(site: str) -> None:
    """Only question 2's citation of what the code does is carved out of trigger (b)."""
    # Arrange
    text = _GATE_SITES[site]()

    # Act
    exceptions = [s for s in _sentences(text) if _TRIGGER_B_EXCEPTION.search(s)]
    wide = [s for s in exceptions if "question 2" not in s]

    # Assert
    assert exceptions, f"the {site} no longer says which citation is not trigger (b)"
    assert not wide, (
        f"the {site} carves out of trigger (b) more than question 2's citation of the code: "
        f"{wide}. Every code line an audit cites 'shows how the code implements the rule', "
        "so a wider exception empties the trigger P1.296's code-line citation should have met."
    )


def test_wave0_review_runs_on_every_verdict_before_the_item_stops() -> None:
    """Step 3a dispatches the Wave 0 reviewer on every verdict, and stops only on a pass."""
    # Arrange
    tokens = _verdict_tokens()
    branches = _step3a_branches()
    assert set(tokens) <= set(branches), (
        f"Step 3a has branches for {sorted(branches)}, not for every verdict {tokens}"
    )

    # Act
    unreviewed = []
    loose_stop = []
    for token in tokens:
        text = _norm(branches[token].replace("*", ""))
        review = text.find("dispatch `reviewer`")
        drop = text.find("agent_status: dropped")
        if review == -1 or (drop != -1 and (drop < review or "on pass" not in text[review:drop])):
            unreviewed.append(token)
        for sentence in _sentences(branches[token]):
            if "stop the item" in sentence and (
                not re.search(r"\bon pass\b", sentence)
                or re.search(r"\b(?:revise|or|either|any)\b", sentence)
            ):
                loose_stop.append((token, sentence))

    # Assert
    assert not unreviewed, (
        f"Step 3a stops or advances {unreviewed} without a passed Wave 0 review. The "
        "scope-and-verb criterion applies on any verdict; a verdict that skips the reviewer "
        "skips it — and a refutation closes its bullet for good at Step 7."
    )
    assert not loose_stop, (
        f"Step 3a stops an item on more than a pass: {loose_stop}. A refutation stopped on a "
        "`revise` is closed at Step 7 although its review never passed."
    )


def test_state_table_pass_row_defers_a_refutation_to_step3a() -> None:
    """The table's `pass` row does not advance a reviewed refutation to Wave 1."""
    # Arrange
    reasons = _step3a_drop_reasons()
    assert reasons, "no Step 3a branch sets a drop reason — nothing for the table to defer to"
    action = _state_table_action(lambda trigger: "worst" in trigger and "`pass`" in trigger)

    # Act
    deferral = _norm(re.split(r"\botherwise\b", action, maxsplit=1, flags=re.IGNORECASE)[0])
    undeferred = sorted(
        token
        for token, reason in reasons.items()
        if not (f"`premise_verdict: {token}`" in deferral and reason in deferral)
        or "not advance" not in deferral
    )

    # Assert
    assert not undeferred, (
        f"the state table's `pass` row advances {undeferred} to the next wave: it does not "
        f"name them with their Step 3a drop reasons {[reasons[t] for t in undeferred]} and "
        "'do not advance' before its 'Otherwise'. Since Step 3a sends a refutation through "
        f"review, the row now sees it ({action[:120]!r}...)."
    )


def test_step7_closes_a_refuted_bullet_only_after_its_review_passed() -> None:
    """Step 7 closes on the passed-review drop reason only, and leaves the table's drops open."""
    # Arrange
    reasons = _step3a_drop_reasons()
    assert reasons, "no Step 3a branch sets a drop reason — nothing for Step 7 to key on"
    wave = _wave0_name()
    table_drops = [f"{reason}-{wave}" for reason in _table_drop_reasons()]
    assert table_drops, 'the state table sets no `drop_reason: "<reason>-<wave>"`'

    # Act
    step7 = _step7_verdict_bullets()
    unkeyed: list[str] = []
    loose_close: list[str] = []
    not_left_open: list[str] = []
    for token, reason in reasons.items():
        sentences = _sentences(step7.get(token, ""))
        closing = [s for s in sentences if "close the bullet" in s]
        if not closing or any(reason not in s for s in closing):
            unkeyed.append(token)
        loose_close += [
            s for s in closing if re.search(r"\bany\b", s) or any(d in s for d in table_drops)
        ]
        not_left_open += [
            drop
            for drop in table_drops
            if not any(drop in s and "leave" in s and "open" in s for s in sentences)
        ]

    # Assert
    assert not unkeyed, (
        f"Step 7 closes the bullet for {unkeyed} without naming the drop reason "
        f"{[reasons[t] for t in unkeyed]} that Step 3a sets only after the Wave 0 review "
        "passed — a refutation that failed its review would be closed anyway."
    )
    assert not loose_close, (
        f"Step 7's closing sentence also closes on other drop reasons: {loose_close}"
    )
    assert not not_left_open, (
        f"Step 7 does not say the bullet of a refutation dropped as {not_left_open} stays "
        "open — a refutation the reviewer never passed would be read as closed."
    )


def test_implement_scenario_step0_applies_the_criterion() -> None:
    """The serial path has no Wave 0 reviewer, so its orchestrator applies the check."""
    # Arrange
    step0 = _norm(_step0())
    cid, _ = _scope_criterion()

    # Act
    names_section = _norm(_scope_section_title()) in step0
    names_criterion = cid.lower() in step0
    refuted_bullet = re.search(r"- `premise: refuted`[^-]*", step0)

    # Assert
    assert names_section and names_criterion, (
        f"/implement-scenario Step 0 does not apply {cid} to the auditor's scope-and-verb "
        "section. Without it the auditor's own criterion is the only gate on that path."
    )
    assert refuted_bullet and cid.lower() in refuted_bullet.group(0), (
        f"/implement-scenario Step 0's `PREMISE: refuted` branch stops without naming {cid}: "
        "a refutation would close its bullet unchecked."
    )


def test_implement_scenario_step0_includes_a_refutation() -> None:
    """Step 0's criterion paragraph names a refutation as included, never as excluded."""
    # Arrange
    sentences = _sentences(_step0_criterion_paragraph())

    # Act
    naming = [s for s in sentences if "`refuted`" in s]
    included = [s for s in naming if "includ" in s]
    carved_out = [s for s in naming if re.search(r"\b(?:exclud\w*|except\w*|skip\w*|not)\b", s)]

    # Assert
    assert included and not carved_out, (
        f"Step 0's {_scope_criterion()[0]} paragraph does not include a `refuted` verdict "
        f"(naming: {naming}). A refutation closes its bullet for good; on this path nothing "
        "else checks it."
    )


def test_auditor_no_longer_denies_the_pra_crm_part() -> None:
    """The stale 'no PRA CRM Part in docs/assets' claim is gone (LESSONS A3, 2026-09-04)."""
    # Arrange
    text = _norm(_read(PREMISE_AUDITOR).replace("*", ""))

    # Act
    stale = re.search(r"\bno pra credit risk mitigation part\b", text)

    # Assert
    assert stale is None, (
        "premise-auditor.md still says docs/assets holds no PRA Credit Risk Mitigation "
        "Part. ps126app1.pdf carries it as a Part of its own; the false caveat tells the "
        "auditor to stop looking."
    )


# --- private helpers ---------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _norm(text: str) -> str:
    """Collapse whitespace and lower-case, so a line wrap cannot hide a phrase."""
    return " ".join(text.split()).lower()


def _sentences(text: str) -> list[str]:
    """Whitespace-normalised, lower-cased sentences, with markdown emphasis removed."""
    flat = " ".join(text.replace("*", "").split())
    return [s.lower() for s in re.split(r"(?<=\.)\s+", flat) if s]


def _paragraphs(text: str) -> list[str]:
    """Blank-line-separated paragraphs of ``text``."""
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _list_after(paragraphs: list[str], index: int) -> list[str]:
    """The numbered-list paragraphs that immediately follow ``paragraphs[index]``."""
    out: list[str] = []
    for paragraph in paragraphs[index + 1 :]:
        if not re.match(r"^\s*\d+\.\s", paragraph):
            break
        out.append(paragraph)
    return out


def _strip_name(text: str) -> str:
    """Drop heading lines and every mention of the section's name, so only requirements remain."""
    title = r"\s+".join(re.escape(word) for word in _scope_section_title().split())
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return re.sub(rf"`?(?:##\s+)?{title}`?", "", "\n".join(lines), flags=re.IGNORECASE)


def _strip_title(text: str) -> str:
    """Drop a leading all-capitals title sentence ("SCOPE SENTENCE AND OPERATIVE VERB.")."""
    match = re.match(r"^([A-Z][A-Z0-9 ,/&'—-]*[A-Z])\.\s+", text)
    if match and len(match.group(1).split()) >= 2:
        return text[match.end() :]
    return text


def _is_floor_finding(sentence: str) -> bool:
    """A sentence saying a floor or max against "shall be assigned" is a finding."""
    return (
        _ASSIGN_VERB in sentence
        and "finding" in sentence
        and bool(re.search(r"\b(?:floor|max)\b", sentence))
    )


def _unfenced_lines(text: str) -> list[str]:
    """The lines of ``text`` that sit outside every ``` fence."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


def _section(text: str, heading: str) -> str:
    """The body under ``heading`` up to the next unfenced heading of the same or higher level."""
    lines = text.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    starts = [i for i, line in enumerate(lines) if line.rstrip() == heading]
    assert len(starts) == 1, f"{heading!r} occurs {len(starts)} times (expected 1)"
    body: list[str] = []
    in_fence = False
    for line in lines[starts[0] + 1 :]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = re.match(r"^(#+)\s", line)
        if not in_fence and match and len(match.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def _first_fence(text: str) -> str:
    match = re.search(r"^```[^\n]*\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    assert match, "no fenced block found"
    return match.group(1)


def _output_fence() -> str:
    return _first_fence(_section(_read(PREMISE_AUDITOR), "## Output format"))


def _output_titles() -> list[str]:
    """The ``## `` section titles the auditor's output format declares."""
    return [
        line.removeprefix("## ").strip()
        for line in _output_fence().splitlines()
        if line.startswith("## ")
    ]


def _scope_section_title() -> str:
    """The auditor's output-format section that names both the scope sentence and the verb."""
    titles = [
        t for t in _output_titles() if _SCOPE_PHRASE in t.lower() and _VERB_PHRASE in t.lower()
    ]
    assert len(titles) == 1, (
        f"premise-auditor.md's output format declares {len(titles)} sections naming both the "
        f"scope sentence and the operative verb (expected 1): {titles}"
    )
    return titles[0]


def _corrected_premise_title() -> str:
    titles = [t for t in _output_titles() if t.lower() == "corrected premise"]
    assert len(titles) == 1, "premise-auditor.md's output format has no Corrected premise section"
    return titles[0]


def _output_placeholder(title: str) -> str:
    """The placeholder lines under one output-format section, its title line excluded."""
    lines = _output_fence().splitlines()
    start = lines.index(f"## {title}")
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _scope_placeholder() -> str:
    return _output_placeholder(_scope_section_title())


def _placeholder_fields(placeholder: str) -> dict[str, str]:
    """``{"label": text}`` for each ``- Label: text`` field, continuation lines included."""
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in placeholder.splitlines():
        match = re.match(r"^- ([A-Za-z][A-Za-z -]*):\s*(.*)$", line)
        if match:
            current = match.group(1).strip().lower()
            fields[current] = [match.group(2)]
        elif current is not None and line.startswith("  "):
            fields[current].append(line)
        else:
            current = None
    return {label: _norm(" ".join(parts)) for label, parts in fields.items()}


def _auditor_criterion() -> str:
    """The body of the one prose section (outside the output fence) naming the operative verb."""
    text = _read(PREMISE_AUDITOR)
    headings = [
        line
        for line in _unfenced_lines(text)
        if line.startswith("## ") and _VERB_PHRASE in line.lower()
    ]
    assert len(headings) == 1, (
        f"premise-auditor.md has {len(headings)} prose sections naming the operative verb "
        "(outside the output-format fence); the criterion needs exactly one home."
    )
    return _section(text, headings[0])


def _verdict_tokens() -> tuple[str, ...]:
    """The verdict tokens, read from the auditor's own ``PREMISE: <a|b|c>`` line."""
    match = re.search(r"^PREMISE: <([a-z|]+)>$", _read(PREMISE_AUDITOR), re.MULTILINE)
    assert match, "premise-auditor.md has no 'PREMISE: <...>' line in its output format"
    return tuple(match.group(1).split("|"))


def _wave0_criteria() -> dict[str, str]:
    """``{"C0.n": body}`` from the fenced block under next-items.md's Wave 0 heading."""
    fence = _first_fence(_section(_read(NEXT_ITEMS), _heading(NEXT_ITEMS, "#### Wave 0")))
    criteria: dict[str, list[str]] = {}
    current: str | None = None
    for line in fence.splitlines():
        match = re.match(r"^(C0\.\d+)\s+—\s+(.*)$", line)
        if match:
            current = match.group(1)
            criteria[current] = [match.group(2)]
        elif current is not None:
            criteria[current].append(line)
    assert criteria, "no C0.n criteria found under the Wave 0 heading"
    return {cid: "\n".join(lines) for cid, lines in criteria.items()}


def _wave0_name() -> str:
    """Wave 0's state-file name, from the waves table (``| 0 | `premise_audit` | ...``)."""
    match = re.search(r"^\| 0 \| `([a-z_]+)` \|", _read(NEXT_ITEMS), re.MULTILINE)
    assert match, "next-items.md's waves table has no Wave 0 row"
    return match.group(1)


def _state_table_rows() -> list[tuple[str, str]]:
    """``(trigger, action)`` for each ``in_review`` row of Step 4b's progression table."""
    rows = []
    for line in _read(NEXT_ITEMS).splitlines():
        match = re.match(r"^\s*\| `agent_status: in_review` \| (.*?) \| (.*) \|\s*$", line)
        if match:
            rows.append((match.group(1), match.group(2)))
    assert rows, "next-items.md has no `agent_status: in_review` progression-table rows"
    return rows


def _state_table_action(matches: Callable[[str], bool]) -> str:
    found = [action for trigger, action in _state_table_rows() if matches(trigger)]
    assert len(found) == 1, f"{len(found)} progression-table rows match (expected 1)"
    return found[0]


def _table_drop_reasons() -> list[str]:
    """The ``<reason>`` of each ``drop_reason: "<reason>-<wave>"`` the table sets."""
    return [
        match.group(1)
        for _, action in _state_table_rows()
        if (match := re.search(r'drop_reason: "([a-z-]+)-<wave>', action))
    ]


def _step3a_branches() -> dict[str, str]:
    """``{verdict: branch text}`` from next-items.md Step 3a's ``- `<verdict>` →`` bullets."""
    lines = _read(NEXT_ITEMS).splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("3a. ")]
    assert len(starts) == 1, f"next-items.md: {len(starts)} lines open Step 3a (expected 1)"
    branches: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[starts[0] + 1 :]:
        if re.match(r"^\d+\.\s", line):
            break
        match = re.match(r"^\s+- `([a-z]+)` →(.*)$", line)
        if match:
            current = match.group(1)
            branches[current] = [match.group(2)]
        elif current is not None and line.strip():
            branches[current].append(line)
        else:
            current = None
    assert branches, "Step 3a has no `- `<verdict>` →` branches"
    return {token: "\n".join(body) for token, body in branches.items()}


def _step3a_drop_reasons() -> dict[str, str]:
    """``{verdict: reason}`` for each Step 3a branch that sets ``drop_reason: "<reason>: ..."``."""
    return {
        token: match.group(1)
        for token, branch in _step3a_branches().items()
        if (match := re.search(r'drop_reason: "([a-z-]+):', branch))
    }


def _step7_verdict_bullets() -> dict[str, str]:
    """``{verdict: bullet text}`` from Step 7's ``- `premise_verdict: <verdict>``` bullets."""
    step7 = _section(_read(NEXT_ITEMS), _heading(NEXT_ITEMS, "## Step 7 "))
    bullets: dict[str, list[str]] = {}
    current: str | None = None
    for line in step7.splitlines():
        match = re.match(r"^- `premise_verdict: ([a-z]+)`(.*)$", line)
        if match:
            current = match.group(1)
            bullets[current] = [match.group(2)]
        elif current is not None and line.startswith("  "):
            bullets[current].append(line)
        else:
            current = None
    return {token: "\n".join(body) for token, body in bullets.items()}


def _step0() -> str:
    return _section(_read(IMPLEMENT_SCENARIO), _heading(IMPLEMENT_SCENARIO, "## Step 0"))


def _step0_criterion_paragraph() -> str:
    """The one Step 0 prose paragraph (not a list item) that names the scope criterion's id."""
    cid, _ = _scope_criterion()
    found = [p for p in _paragraphs(_step0()) if cid in p and not p.lstrip().startswith("- ")]
    assert len(found) == 1, f"{len(found)} Step 0 prose paragraphs name {cid} (expected 1)"
    return found[0]


def _heading(path: Path, prefix: str) -> str:
    """The one heading line in ``path`` that starts with ``prefix``."""
    found = [line.rstrip() for line in _read(path).splitlines() if line.startswith(prefix)]
    assert len(found) == 1, f"{path.name}: {len(found)} headings start {prefix!r}"
    return found[0]


def _scope_criterion() -> tuple[str, str]:
    title = _norm(_scope_section_title())
    naming = [(cid, b) for cid, b in _wave0_criteria().items() if title in _norm(b)]
    assert len(naming) == 1, f"{len(naming)} Wave 0 criteria name {title!r} (expected 1)"
    return naming[0]


def _one_sentence(sentences: list[str], keep: Callable[[str], bool], where: str) -> str:
    found = [s for s in sentences if keep(s)]
    assert len(found) == 1, f"{where}: {len(found)} sentences match (expected 1): {found}"
    return found[0]


def _auditor_fail_sentence() -> str:
    return _one_sentence(
        _sentences(_auditor_criterion()),
        lambda s: s.startswith("it fails"),
        "the auditor criterion's 'It fails' sentence",
    )


def _c09_revise_sentence() -> str:
    return _one_sentence(
        _sentences(_strip_title(" ".join(_scope_criterion()[1].split()))),
        lambda s: s.startswith("`revise` if"),
        "the scope criterion's '`revise` if' sentence",
    )


def _step0_fail_sentence() -> str:
    return _one_sentence(
        _sentences(_step0_criterion_paragraph()),
        lambda s: "re-invoke" in s,
        "Step 0's re-invoke sentence",
    )


_FAIL_SENTENCES: dict[str, Callable[[], str]] = {
    "auditor criterion": _auditor_fail_sentence,
    "C0.9 revise": _c09_revise_sentence,
    "implement-scenario Step 0": _step0_fail_sentence,
}

_GATE_SITES: dict[str, Callable[[], str]] = {
    "C0.9": lambda: _scope_criterion()[1],
    "auditor criterion": _auditor_criterion,
    "auditor output placeholder": _scope_placeholder,
    "implement-scenario Step 0": _step0_criterion_paragraph,
}


def _verdict_gate(body: str, tokens: tuple[str, ...]) -> str | None:
    """The first sentence that restricts the criterion to a PREMISE verdict, else ``None``.

    Checked in every sentence after a leading title sentence is dropped:

    - a clause that opens "For `<token>`" (C0.5's gate);
    - "only ... `<token>`" not preceded by "not" ("applies only when the verdict
      is `refuted`"; "not only `refuted`" widens rather than gates);
    - "`<token>` ... only" (the Corrected-premise placeholder's
      "`refuted` and `rescoped` only");
    - "verdict is `<token>`" ("when / if the verdict is `refuted`");
    - "on / for / to a `<token>` ... verdict" ("triggered on a `refuted`
      verdict").
    """
    text = _strip_title(" ".join(body.split()))
    for sentence in _sentences(text):
        for token in tokens:
            tok = re.escape(f"`{token}`")
            shapes = (
                rf"(?:^|[:;(<]\s*)for {tok}",
                rf"(?<!not )\bonly\b[^.;:]*{tok}",
                rf"{tok}[^.;:]*\bonly\b",
                rf"\bverdict is (?:an? )?{tok}",
                rf"\b(?:on|for|to) (?:an? |the )?{tok}[^.;:]*\bverdict\b",
            )
            if any(re.search(shape, sentence) for shape in shapes):
                return sentence
    return None
