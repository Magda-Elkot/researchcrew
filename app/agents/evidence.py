"""Evidence integrity: keep only evidence that really came from a tool (DECISIONS #70).

In the 3a spike the model cited a URL it never fetched and figures that were in no tool result.
So every `EvidenceItem` is checked in Python against the tool results recorded by the same
research task: its snippet must appear verbatim in one result, and its source (URL or doc_id)
must appear in that same result. Both sides are normalised the same way first, so harmless
differences (escaped newlines, spacing, case, Arabic diacritics or presentation forms) don't
drop real evidence.

The Researcher answers in a small labelled text format (`source_type:`, `source:`, `claim:`,
`snippet:`), not JSON: asked for a JSON schema while it had tools, gpt-oss on Groq sometimes
"answered" by calling a non-existent tool named `json`, and Groq rejected the run (DECISIONS #75).
`parse_evidence_text` reads that format (JSON is still accepted).

`make_evidence_guardrail` turns the check into a CrewAI task guardrail: it returns the cleaned
`EvidenceSet` as JSON, which CrewAI uses as the task output the next agents see.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.log import get_logger
from app.schemas import EvidenceItem, EvidenceSet

logger = get_logger(__name__)

MIN_SNIPPET_CHARS = 20  # shorter "snippets" ("the GCC") would match almost anything

_ARABIC_MARKS = re.compile("[ـً-ْٰ]")  # tatweel, harakat, superscript alef
_JSON_ESCAPES = (("\\n", " "), ("\\t", " "), ("\\r", " "), ('\\"', '"'), ("\\/", "/"))
_SPACES = re.compile(r"\s+")
# Typographic look-alikes models like to "correct" when quoting: every quote mark becomes ',
# every dash or hyphen becomes -. Quote style and dash length carry no meaning here.
_TYPOGRAPHY = str.maketrans(
    {
        '"': "'", "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": "'", "\u201d": "'", "\u201e": "'", "\u00ab": "'", "\u00bb": "'",
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2212": "-",
    }
)  # fmt: skip
# NFKC turns "…" into "...": a snippet may skip text there (a quote with an ellipsis).
_ELLIPSIS = re.compile(r"\s*\.\.\.+\s*")
_EDGES = " \"'.,;:-"


def normalize(text: str) -> str:
    """The form both snippets and tool results are compared in."""
    for escape, plain in _JSON_ESCAPES:
        text = text.replace(escape, plain)
    text = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)
    text = _ARABIC_MARKS.sub("", text)
    return _SPACES.sub(" ", text).strip().casefold()


def fragments(snippet: str) -> list[str]:
    """The verbatim pieces of a (normalised) snippet, split where it uses an ellipsis."""
    pieces = (piece.strip(_EDGES) for piece in _ELLIPSIS.split(snippet))
    return [piece for piece in pieces if piece]


def _contains_in_order(text: str, pieces: list[str]) -> bool:
    position = 0
    for piece in pieces:
        found = text.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    return True


def _normalize_source(source: str) -> str:
    """URLs are compared without scheme, `www.` and trailing slash."""
    value = normalize(source)
    value = re.sub(r"^https?://", "", value)
    value = value.removeprefix("www.")
    return value.rstrip("/")


_FIELD = re.compile(
    r"^[\s>*\-•]*\**(source_type|source|claim|snippet)\**\s*[:\uff1a]\s*(.*)$", re.IGNORECASE
)
_FENCE = re.compile(r"^```\w*\s*|\s*```$")


def _unquote(value: str) -> str:
    value = value.strip().strip("*").strip()
    for left, right in (('"', '"'), ("“", "”"), ("'", "'"), ("«", "»")):
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            return value[1:-1].strip()
    return value


def _to_item(fields: dict[str, str], sub_question_id: str, n: int) -> EvidenceItem | None:
    source = _unquote(fields.get("source", ""))
    source_type = _unquote(fields.get("source_type", "")).lower()
    if source_type not in ("doc", "web"):
        source_type = "web" if source.startswith(("http://", "https://")) else "doc"
    try:
        return EvidenceItem(
            id=f"raw{n}",
            sub_question_id=sub_question_id,
            claim=_unquote(fields.get("claim", "")),
            snippet=_unquote(fields.get("snippet", "")),
            source_type=source_type,  # type: ignore[arg-type]  # checked just above
            source=source,
        )
    except ValidationError:
        return None  # a block with a missing claim or source


def parse_evidence_text(raw: str, sub_question_id: str) -> list[EvidenceItem]:
    """Read the Researcher's answer: labelled blocks, or an EvidenceSet as JSON."""
    text = _FENCE.sub("", raw.strip())
    if text.startswith("{"):
        try:
            return EvidenceSet.model_validate_json(text).items
        except ValidationError:
            pass  # fall through to the text format

    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            key = match.group(1).lower()
            if key in current or (key == "source_type" and current):
                blocks.append(current)
                current = {}
            current[key] = match.group(2).strip()
            last_key = key
        elif last_key and line.strip() and current:
            current[last_key] += " " + line.strip()  # a value that wraps onto the next line
    if current:
        blocks.append(current)

    items = [_to_item(block, sub_question_id, n) for n, block in enumerate(blocks, start=1)]
    return [item for item in items if item is not None]


@dataclass
class EvidenceCheck:
    kept: list[EvidenceItem] = field(default_factory=list)
    dropped: list[tuple[EvidenceItem, str]] = field(default_factory=list)


def _why_not_grounded(item: EvidenceItem, outputs: list[str]) -> str | None:
    """None if the item is grounded in one output, else the reason it isn't.

    Every piece of the snippet (split at "...") must appear verbatim, in order, in one tool
    result, and at least one piece must be long enough to be meaningful on its own.
    """
    pieces = fragments(normalize(item.snippet))
    if not any(len(piece) >= MIN_SNIPPET_CHARS for piece in pieces):
        return "snippet too short"
    source = _normalize_source(item.source)
    matches = [out for out in outputs if _contains_in_order(out, pieces)]
    if not matches:
        return "snippet not found in any tool result"
    if not any(source in out for out in matches):
        return "source not found in the tool result that holds the snippet"
    return None


def check_evidence(
    items: list[EvidenceItem],
    outputs: list[str],
    sub_question_id: str,
    max_items: int,
    snippet_max_chars: int,
) -> EvidenceCheck:
    """Keep grounded, distinct items (at most `max_items`), with stable ids `<sq>-e<n>`.

    Kept snippets are cut to `snippet_max_chars` (a prefix of verbatim text stays verbatim).
    """
    normalized_outputs = [normalize(out) for out in outputs]
    check = EvidenceCheck()
    seen: set[str] = set()
    for item in items:
        reason = _why_not_grounded(item, normalized_outputs)
        if reason is None and normalize(item.snippet) in seen:
            reason = "duplicate snippet"
        if reason is None and len(check.kept) >= max_items:
            reason = "over the per-sub-question limit"
        if reason is not None:
            check.dropped.append((item, reason))
            continue
        seen.add(normalize(item.snippet))
        check.kept.append(
            item.model_copy(
                update={
                    "id": f"{sub_question_id}-e{len(check.kept) + 1}",
                    "sub_question_id": sub_question_id,
                    "snippet": item.snippet[:snippet_max_chars],
                }
            )
        )
    for item, reason in check.dropped:
        logger.warning(
            "evidence dropped",
            extra={
                "sub_question_id": sub_question_id,
                "source": item.source,
                "reason": reason,
                "snippet": item.snippet[:160],
            },
        )
    return check


def make_evidence_guardrail(
    outputs_for: Callable[[], list[str]],
    sub_question_id: str,
    max_items: int,
    snippet_max_chars: int,
    on_checked: Callable[[EvidenceCheck], None] | None = None,
) -> Callable[[Any], tuple[bool, Any]]:
    """A CrewAI task guardrail for one research task.

    `outputs_for` returns that task's recorded tool results (read when the task finishes).
    The guardrail never asks for a retry (that would cost a whole extra agent run); an
    unreadable answer simply yields no evidence.
    """

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        if isinstance(task_output.pydantic, EvidenceSet):
            items = task_output.pydantic.items
        else:
            items = parse_evidence_text(task_output.raw or "", sub_question_id)
        check = check_evidence(items, outputs_for(), sub_question_id, max_items, snippet_max_chars)
        if not items or any(reason == "snippet too short" for _, reason in check.dropped):
            # Show the answer so a format problem can be seen and fixed (model text, no secrets).
            logger.warning(
                "research answer hard to read",
                extra={"sq": sub_question_id, "answer": (task_output.raw or "")[:1500]},
            )
        if on_checked is not None:
            on_checked(check)
        return True, EvidenceSet(items=check.kept).model_dump_json()

    return guardrail
