"""
The Bank of England's validation-rule language — lexer, parser and syntax tree.

Pipeline position:
    rule workbook cell (Scope / Where / Join / Expression)
        -> parse_expression | parse_scope | parse_join  ->  syntax tree
        -> boe.engine (evaluation)

Key responsibilities:
- Parse the RAW ``Expression`` cell of a rule, exactly as published. The raw
  cell is the authoritative statement of a rule: it carries, per reference,
  what an unreported cell is taken to be (``dv``) and whether the reference
  binds one cell at a time or all of them (``seq``), and per operator whether
  the comparison allows for rounding (the ``i`` prefix). The workbook's
  ``Simplified Expression`` drops all three.
- Produce a typed, immutable tree in which every operator's interval flag, every
  reference's keys and every default are explicit, so the engine never has to
  look at rule text.
- Refuse what it does not understand, with the position — never guess.

The language (measured over all 3,813 rules of the v4.1.1 workbooks)

    expr      = if_expr | or_expr
    if_expr   = IF expr THEN expr [ ELSE expr ]        (no ELSE means "else true")
    or_expr   = and_expr { OR and_expr }
    and_expr  = cmp_expr { AND cmp_expr }
    cmp_expr  = add_expr [ [i] (= | != | <= | >= | < | >) add_expr ]   (never chained)
    add_expr  = mul_expr { [i] (+ | -) mul_expr }      (left-associative)
    mul_expr  = unary { [i] (* | /) unary }            (left-associative)
    unary     = - unary | primary
    primary   = NUMBER | STRING | [member] | {reference} | name( args ) | ( expr )

Keywords and function names are case-insensitive. A string is a double-quoted
regular expression and may itself contain braces, so strings are lexed before
references.

References:
- Bank of England Banking Taxonomy v4.1.1 — validation rule workbooks, "Note"
  sheet (the publisher's syntax summary)
- The grammar was proved against the taxonomy: for every rule that has a
  formula file, this tree equals the tree of the XPath test Arelle executes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# =============================================================================
# Constants
# =============================================================================

#: Comparison operators, longest first so ``<=`` is not read as ``<``.
COMPARISONS: Final = ("!=", "<=", ">=", "=", "<", ">")

#: The member that stands for "no member reported" in an enumeration default.
DEFAULT_MEMBER: Final = "Default"

DEFAULT_ZERO: Final = "zero"
DEFAULT_EMPTY: Final = "empty"
DEFAULT_FALSE: Final = "false"
DEFAULT_MEMBER_KIND: Final = "member"
DEFAULT_STRING: Final = "string"
DEFAULT_DATE: Final = "date"

_KEYWORDS: Final = frozenset({"if", "then", "else", "and", "or"})
_OPERATOR_CHARS: Final = "=!<>+-*/"
_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_NUMBER: Final = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_REFERENCE_KEY: Final = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$", re.DOTALL)
_CREATE_DATE: Final = re.compile(
    r"^CreateDate\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)$", re.I
)
_CODE: Final = re.compile(r"^\d{3,4}$")


# =============================================================================
# The syntax tree
# =============================================================================


class GrammarError(ValueError):
    """A rule cell that is not in the language. Carries the offending position."""

    def __init__(self, message: str, position: int = -1) -> None:
        super().__init__(message)
        self.position = position


@dataclass(frozen=True)
class Number:
    """A numeric literal. It is exact: it carries no rounding allowance."""

    value: float


@dataclass(frozen=True)
class Text:
    """A string literal — in practice a regular expression for ``matches``."""

    value: str


@dataclass(frozen=True)
class Member:
    """An enumeration member, e.g. ``eba_GA:x1``; ``Default`` is "none reported"."""

    qname: str


@dataclass(frozen=True)
class DimensionFilter:
    """A reference restricted by the member of a dimension, or of the cell itself.

    ``dim(this(), [D]) = [M]`` restricts the cells to those reported under
    member ``M`` of dimension ``D`` — in table terms, to one sheet of an open
    axis. ``negated`` is its complement. With ``dimension`` ``None`` the filter
    is on the cell's own value (``this() = [M]``).
    """

    dimension: str | None
    member: str
    negated: bool = False


@dataclass(frozen=True)
class Default:
    """What a reference is taken to be where its cell is not reported.

    ``kind`` is one of the ``DEFAULT_*`` constants. ``value`` holds the member
    for ``member`` and the ISO date for ``date``; it is ``None`` otherwise.
    """

    kind: str
    value: str | None = None


@dataclass(frozen=True)
class Reference:
    """A cell reference, ``{t: .., r: .., c: .., z: .., dv: .., seq: .., id: ..}``.

    Attributes:
        table: The table code. ``None`` only inside a scope-relative rule.
        rows / columns / sheets: The codes given, in order and as written;
            empty where the reference leaves the axis open. Most tables write
            four digits and some three, so a code is matched to its table's own
            when the reference is resolved, not here.
        default: What an unreported cell is taken to be; ``None`` means the
            reference has NO default — the rule is not evaluated where the cell
            is not reported.
        dimension_filter: A restriction on an open axis's member or on the
            cell's own value.
        sequence: ``True`` binds every matching cell at once (for a sum, a
            count); ``False`` binds one cell at a time.
        variable: The publisher's variable name (``v0``); the same name on two
            references marks one cell used twice.
        key_dimension: Set for the ``{d: [dimension], ..}`` form, which stands
            for a row's key value rather than a cell.
    """

    table: str | None
    rows: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    default: Default | None = None
    dimension_filter: DimensionFilter | None = None
    sequence: bool = False
    variable: str | None = None
    key_dimension: str | None = None


@dataclass(frozen=True)
class Call:
    """A function call. ``name`` is lower-cased."""

    name: str
    arguments: tuple[Node, ...]


@dataclass(frozen=True)
class Negate:
    """Unary minus."""

    operand: Node


@dataclass(frozen=True)
class Binary:
    """An arithmetic or comparison operator.

    ``interval`` is the ``i`` prefix: the operation carries each operand's
    rounding allowance instead of comparing reported values exactly.
    """

    operator: str
    left: Node
    right: Node
    interval: bool = False

    @property
    def is_comparison(self) -> bool:
        return self.operator in COMPARISONS


@dataclass(frozen=True)
class Logical:
    """``and`` / ``or`` over two or more operands."""

    operator: str
    operands: tuple[Node, ...]


@dataclass(frozen=True)
class Conditional:
    """``if .. then .. [else ..]``. A missing ``else`` is ``true``."""

    condition: Node
    then: Node
    otherwise: Node | None = None


Node = Number | Text | Member | Reference | Call | Negate | Binary | Logical | Conditional


@dataclass(frozen=True)
class ScopeGroup:
    """One table's part of a rule's scope: the codes the rule is run for, per axis."""

    table: str
    rows: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()


@dataclass(frozen=True)
class JoinKey:
    """``JoinDimensions({ref}, [D])`` — the reference is keyed by dimension ``D``."""

    reference: Reference
    dimension: str


@dataclass(frozen=True)
class JoinEquality:
    """``dim({A}, [D1]) = dim({B}, [D2])`` — two references' rows matched by key."""

    left: Reference
    left_dimension: str
    right: Reference
    right_dimension: str


# =============================================================================
# Public API
# =============================================================================


def parse_expression(text: str) -> Node:
    """Parse an ``Expression`` or ``Where`` cell.

    Raises:
        GrammarError: the cell is not in the language.
    """
    parser = _Parser(text)
    node = parser.expression()
    parser.expect_end()
    return node


def parse_scope(text: str) -> tuple[ScopeGroup, ...]:
    """Parse a ``Scope`` cell, ``scope({t: .., c: ..}[, {..}])``. Empty text is no scope."""
    if not text or not text.strip():
        return ()
    node = parse_expression(text)
    if not isinstance(node, Call) or node.name != "scope" or not node.arguments:
        raise GrammarError("a scope cell must read scope({..}[, {..}])")
    groups: list[ScopeGroup] = []
    for argument in node.arguments:
        if not isinstance(argument, Reference) or argument.table is None:
            raise GrammarError("a scope names tables: scope({t: TABLE, ..})")
        groups.append(ScopeGroup(argument.table, argument.rows, argument.columns, argument.sheets))
    return tuple(groups)


def parse_join(text: str) -> tuple[JoinKey | JoinEquality, ...]:
    """Parse a ``Join`` cell, ``join(JoinDimensions(..) | dim(..) = dim(..), ..)``."""
    if not text or not text.strip():
        return ()
    node = parse_expression(text)
    if not isinstance(node, Call) or node.name != "join" or not node.arguments:
        raise GrammarError("a join cell must read join(..)")
    return tuple(_join_item(argument) for argument in node.arguments)


def references(node: Node) -> tuple[Reference, ...]:
    """Every reference in ``node``, in the order written."""
    found: list[Reference] = []
    _collect(node, found)
    return tuple(found)


# =============================================================================
# Private helpers — lexer
# =============================================================================


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    position: int
    interval: bool = False


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
        elif char == '"':
            end = text.find('"', index + 1)
            if end < 0:
                raise GrammarError("unterminated string", index)
            tokens.append(_Token("string", text[index + 1 : end], index))
            index = end + 1
        elif char == "{":
            end = _reference_end(text, index)
            tokens.append(_Token("reference", text[index : end + 1], index))
            index = end + 1
        elif char == "[" or text.startswith("$[", index):
            end = text.find("]", index)
            if end < 0:
                raise GrammarError("unterminated [member]", index)
            tokens.append(_Token("member", text[text.index("[", index) + 1 : end].strip(), index))
            index = end + 1
        elif char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            match = _NUMBER.match(text, index)
            if match is None:
                raise GrammarError("malformed number", index)
            tokens.append(_Token("number", match.group(), index))
            index = match.end()
        elif char.isalpha() or char == "_":
            match = _NAME.match(text, index)
            if match is None:  # pragma: no cover - isalpha guarantees a match
                raise GrammarError("malformed name", index)
            word, end = match.group(), match.end()
            # The interval prefix is a bare "i" glued to an operator.
            if word in ("i", "I") and end < length and text[end] in _OPERATOR_CHARS:
                operator = _operator_at(text, end)
                tokens.append(_Token("operator", operator, index, interval=True))
                index = end + len(operator)
            else:
                kind = "keyword" if word.lower() in _KEYWORDS else "name"
                tokens.append(_Token(kind, word.lower() if kind == "keyword" else word, index))
                index = end
        elif char in _OPERATOR_CHARS:
            operator = _operator_at(text, index)
            tokens.append(_Token("operator", operator, index))
            index += len(operator)
        elif char in "(),":
            tokens.append(_Token(char, char, index))
            index += 1
        else:
            raise GrammarError(f"unexpected character {char!r}", index)
    return tokens


def _operator_at(text: str, index: int) -> str:
    for operator in ("!=", "<=", ">="):
        if text.startswith(operator, index):
            return operator
    return text[index]


def _reference_end(text: str, start: int) -> int:
    """Index of the ``}`` closing the ``{`` at ``start``. Strings inside are skipped."""
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == '"':
            end = text.find('"', index + 1)
            if end < 0:
                raise GrammarError("unterminated string inside a reference", index)
            index = end + 1
            continue
        if char == "{":
            raise GrammarError("a reference inside a reference", index)
        if char == "}":
            return index
        index += 1
    raise GrammarError("unterminated reference", start)


# =============================================================================
# Private helpers — parser
# =============================================================================


class _Parser:
    """Recursive descent over the token list; one method per grammar production."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = _lex(text)
        self._index = 0

    def expect_end(self) -> None:
        token = self._peek()
        if token is not None:
            raise GrammarError(f"unexpected {token.text!r} after the expression", token.position)

    def expression(self) -> Node:
        if self._is_keyword("if"):
            return self._conditional()
        return self._logical("or", lambda: self._logical("and", self._comparison))

    def _conditional(self) -> Node:
        self._next()
        condition = self.expression()
        if not self._is_keyword("then"):
            raise GrammarError("expected 'then'", self._position())
        self._next()
        then = self.expression()
        otherwise = None
        if self._is_keyword("else"):
            self._next()
            otherwise = self.expression()
        return Conditional(condition, then, otherwise)

    def _logical(self, keyword: str, operand) -> Node:  # noqa: ANN001 - a production
        operands = [operand()]
        while self._is_keyword(keyword):
            self._next()
            operands.append(operand())
        return operands[0] if len(operands) == 1 else Logical(keyword, tuple(operands))

    def _comparison(self) -> Node:
        left = self._additive()
        token = self._peek()
        if token is None or token.kind != "operator" or token.text not in COMPARISONS:
            return left
        self._next()
        node = Binary(token.text, left, self._additive(), token.interval)
        following = self._peek()
        if following is not None and following.kind == "operator" and following.text in COMPARISONS:
            raise GrammarError("a comparison cannot be chained", following.position)
        return node

    def _additive(self) -> Node:
        node = self._multiplicative()
        while (
            (token := self._peek()) is not None and token.kind == "operator" and token.text in "+-"
        ):
            self._next()
            node = Binary(token.text, node, self._multiplicative(), token.interval)
        return node

    def _multiplicative(self) -> Node:
        node = self._unary()
        while (
            (token := self._peek()) is not None and token.kind == "operator" and token.text in "*/"
        ):
            self._next()
            node = Binary(token.text, node, self._unary(), token.interval)
        return node

    def _unary(self) -> Node:
        token = self._peek()
        if (
            token is not None
            and token.kind == "operator"
            and token.text == "-"
            and not token.interval
        ):
            self._next()
            return Negate(self._unary())
        return self._primary()

    def _primary(self) -> Node:
        token = self._next()
        if token.kind == "number":
            return Number(float(token.text))
        if token.kind == "string":
            return Text(token.text)
        if token.kind == "member":
            return Member(token.text)
        if token.kind == "reference":
            return _parse_reference(token.text, token.position)
        if token.kind == "(":
            inner = self.expression()
            self._expect(")")
            return inner
        if token.kind == "name":
            self._expect("(", f"{token.text!r} is not followed by '('")
            arguments: list[Node] = []
            if (closing := self._peek()) is not None and closing.kind == ")":
                self._next()
                return Call(token.text.lower(), ())
            arguments.append(self.expression())
            while (comma := self._peek()) is not None and comma.kind == ",":
                self._next()
                arguments.append(self.expression())
            self._expect(")")
            return Call(token.text.lower(), tuple(arguments))
        raise GrammarError(f"unexpected {token.text!r}", token.position)

    def _peek(self) -> _Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _next(self) -> _Token:
        token = self._peek()
        if token is None:
            raise GrammarError("the expression ends too soon", len(self._text))
        self._index += 1
        return token

    def _expect(self, kind: str, message: str | None = None) -> None:
        token = self._peek()
        if token is None or token.kind != kind:
            raise GrammarError(message or f"expected {kind!r}", self._position())
        self._index += 1

    def _is_keyword(self, word: str) -> bool:
        token = self._peek()
        return token is not None and token.kind == "keyword" and token.text == word

    def _position(self) -> int:
        token = self._peek()
        return token.position if token is not None else len(self._text)


# =============================================================================
# Private helpers — references, defaults, filters, joins
# =============================================================================


def _parse_reference(text: str, position: int) -> Reference:
    parts: dict[str, str] = {}
    positional: list[str] = []
    for raw in _split_top_level(text[1:-1]):
        part = raw.strip()
        if not part:
            raise GrammarError("an empty part in a reference", position)
        match = _REFERENCE_KEY.match(part)
        if match is None:
            positional.append(part)
            continue
        key = match.group(1)
        if key in parts:
            raise GrammarError(f"key {key!r} given twice in a reference", position)
        parts[key] = match.group(2).strip()

    unknown = set(parts) - {"t", "r", "c", "z", "x", "d", "dv", "filter", "seq", "id", "f", "fv"}
    if unknown:
        raise GrammarError(f"unknown reference key(s) {sorted(unknown)}", position)
    if "d" in parts:
        return Reference(
            table=None,
            default=_parse_default(parts["dv"], position) if "dv" in parts else None,
            sequence=_parse_flag(parts.get("seq", "False"), position),
            variable=parts.get("id"),
            key_dimension=_parse_member(parts["d"], position),
        )
    # The legacy form ``{TABLE, x: 010}`` names the table positionally.
    table = parts.get("t") or (positional[0] if len(positional) == 1 else None)
    if len(positional) > (0 if "t" in parts else 1):
        raise GrammarError(f"unexpected {positional!r} in a reference", position)
    return Reference(
        table=table,
        rows=_codes(parts.get("r"), position),
        columns=_codes(parts.get("c") or parts.get("x"), position),
        sheets=_codes(parts.get("z"), position),
        default=_parse_default(parts["dv"], position) if "dv" in parts else None,
        dimension_filter=_parse_filter(parts["filter"], position) if "filter" in parts else None,
        sequence=_parse_flag(parts.get("seq", "False"), position),
        variable=parts.get("id"),
    )


def _split_top_level(body: str) -> list[str]:
    """Split on commas that are outside parentheses, brackets and strings."""
    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(body):
        char = body[index]
        if char == '"':
            end = body.find('"', index + 1)
            end = len(body) - 1 if end < 0 else end
            current.append(body[index : end + 1])
            index = end + 1
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            pieces.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    pieces.append("".join(current))
    return pieces


def _codes(value: str | None, position: int) -> tuple[str, ...]:
    if value is None:
        return ()
    codes = tuple(code.strip() for code in value.split(";"))
    for code in codes:
        if not _CODE.match(code):
            raise GrammarError(f"{code!r} is not a row, column or sheet code", position)
    return codes


def _parse_flag(value: str, position: int) -> bool:
    folded = value.strip().lower()
    if folded not in ("true", "false"):
        raise GrammarError(f"seq must be True or False, not {value!r}", position)
    return folded == "true"


def _parse_member(value: str, position: int) -> str:
    text = value.strip()
    if text.startswith("$"):
        text = text[1:]
    if not (text.startswith("[") and text.endswith("]")):
        raise GrammarError(f"expected a [member], found {value!r}", position)
    return text[1:-1].strip()


def _parse_default(value: str, position: int) -> Default:
    text = value.strip()
    folded = text.replace(" ", "").lower()
    if folded == "0":
        return Default(DEFAULT_ZERO)
    if folded == "emptysequence()":
        return Default(DEFAULT_EMPTY)
    if folded == "false()":
        return Default(DEFAULT_FALSE)
    if folded in ('""', "\"''\""):
        return Default(DEFAULT_STRING)
    if text.startswith("[") or text.startswith("$["):
        return Default(DEFAULT_MEMBER_KIND, _parse_member(text, position))
    date = _CREATE_DATE.match(text)
    if date is not None:
        year, month, day = (int(group) for group in date.groups())
        return Default(DEFAULT_DATE, f"{year:04d}-{month:02d}-{day:02d}")
    raise GrammarError(f"unknown default value {value!r}", position)


def _parse_filter(value: str, position: int) -> DimensionFilter:
    node = parse_expression(value)
    negated = False
    if isinstance(node, Call) and node.name == "not" and len(node.arguments) == 1:
        negated, node = True, node.arguments[0]
    if not isinstance(node, Binary) or node.operator != "=" or not isinstance(node.right, Member):
        raise GrammarError(f"unsupported filter {value!r}", position)
    target = node.left
    if isinstance(target, Call) and target.name == "this" and not target.arguments:
        return DimensionFilter(None, node.right.qname, negated)
    if (
        isinstance(target, Call)
        and target.name == "dim"
        and len(target.arguments) == 2
        and isinstance(target.arguments[0], Call)
        and target.arguments[0].name == "this"
        and isinstance(target.arguments[1], Member)
    ):
        return DimensionFilter(target.arguments[1].qname, node.right.qname, negated)
    raise GrammarError(f"unsupported filter {value!r}", position)


def _join_item(node: Node) -> JoinKey | JoinEquality:
    if (
        isinstance(node, Call)
        and node.name == "joindimensions"
        and len(node.arguments) == 2
        and isinstance(node.arguments[0], Reference)
        and isinstance(node.arguments[1], Member)
    ):
        return JoinKey(node.arguments[0], node.arguments[1].qname)
    if isinstance(node, Binary) and node.operator == "=":
        left, right = _dim_of(node.left), _dim_of(node.right)
        if left is not None and right is not None:
            return JoinEquality(left[0], left[1], right[0], right[1])
    raise GrammarError("a join item must be JoinDimensions({..}, [D]) or dim(..) = dim(..)")


def _dim_of(node: Node) -> tuple[Reference, str] | None:
    if (
        isinstance(node, Call)
        and node.name == "dim"
        and len(node.arguments) == 2
        and isinstance(node.arguments[0], Reference)
        and isinstance(node.arguments[1], Member)
    ):
        return node.arguments[0], node.arguments[1].qname
    return None


def _collect(node: Node, found: list[Reference]) -> None:
    if isinstance(node, Reference):
        found.append(node)
    elif isinstance(node, Call):
        for argument in node.arguments:
            _collect(argument, found)
    elif isinstance(node, Negate):
        _collect(node.operand, found)
    elif isinstance(node, Binary):
        _collect(node.left, found)
        _collect(node.right, found)
    elif isinstance(node, Logical):
        for operand in node.operands:
            _collect(operand, found)
    elif isinstance(node, Conditional):
        _collect(node.condition, found)
        _collect(node.then, found)
        if node.otherwise is not None:
            _collect(node.otherwise, found)
