"""LLM-as-judge: faithfulness and completeness scores, 1-5 (SPEC; DECISIONS #5, #98, #101).

The judge is a different provider and model family from the generator (Gemini vs Groq
gpt-oss), to reduce self-grading bias.

- Faithfulness: each cited claim is shown with the **raw tool output** behind its evidence
  (a window around the place where the evidence snippet occurs), not the Researcher's snippet,
  so an invented snippet can't support an invented claim. Scores are averaged per run.
- Completeness: the judge marks each of the question's `expected_aspects` (written by hand
  for the dataset, not the Planner's own sub-questions) as covered yes/partly/no; the 1-5 score
  is computed from those verdicts.

Answers must be JSON matching the Pydantic models below; an unreadable answer is retried once.
The LLM call itself is injected (`CompleteFn`), so tests never call a real model.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.agents.evidence import fragments, normalize
from app.agents.pipeline import ToolCall
from app.config import Settings
from app.log import get_logger
from app.schemas import EvidenceItem, Report
from evals.metrics import report_claims

logger = get_logger(__name__)

MAX_CLAIMS = 25  # bounds the prompt; longer reports are judged on their first 25 claims

CompleteFn = Callable[[str, str], str]  # (system prompt, user prompt) -> model text


class JudgeError(RuntimeError):
    """The judge's answer could not be read, even after one retry."""


# --- answers ----------------------------------------------------------------------------


class ClaimScore(BaseModel):
    claim: int
    score: int = Field(ge=1, le=5)
    reason: str = ""


class FaithfulnessAnswer(BaseModel):
    scores: list[ClaimScore]


class AspectVerdict(BaseModel):
    aspect: int
    covered: Literal["yes", "partly", "no"]


class CompletenessAnswer(BaseModel):
    aspects: list[AspectVerdict]
    score: int = Field(ge=1, le=5)
    reason: str = ""


# --- prompts ----------------------------------------------------------------------------

FAITHFULNESS_SYSTEM = """You check whether claims in a research report are supported by their
sources. For each claim you get the source text it cites (raw text returned by a search
tool; it may be lowercased and may be in English or Arabic). Judge only against that
source text, not your own knowledge. Score each claim:
5 = fully supported; 4 = supported, minor imprecision; 3 = partly supported;
2 = mostly unsupported; 1 = contradicted or not in the source.
Answer only with JSON: {"scores": [{"claim": <number>, "score": <1-5>, "reason": "<short>"}]}"""

COMPLETENESS_SYSTEM = """You check whether a research report answers its question completely.
You get the question, the report and the key aspects a complete answer covers. For each aspect
decide whether the report covers it: "yes", "partly" or "no". Then score the whole report:
5 = all aspects covered; 4 = most; 3 = about half; 2 = few; 1 = none.
The report may be in English or Arabic.
Answer only with JSON: {"aspects": [{"aspect": <number>, "covered": "yes|partly|no"}],
"score": <1-5>, "reason": "<short>"}"""


# --- source windows ---------------------------------------------------------------------


def source_window(evidence: EvidenceItem, tool_log: list[ToolCall], chars: int) -> str:
    """The raw tool output around the evidence snippet (normalised text), or the snippet
    itself, marked, if no output of the same research task contains it."""
    pieces = fragments(normalize(evidence.snippet))
    for call in tool_log:
        if not call.ok or call.scope != evidence.sub_question_id or not pieces:
            continue
        text = normalize(call.output)
        position = text.find(pieces[0])
        if position >= 0:
            start = max(0, position - chars // 3)
            return text[start : start + chars]
    return f"(snippet only) {evidence.snippet}"


@dataclass
class ClaimToJudge:
    text: str
    sources: list[str]


def claims_to_judge(
    report: Report, evidence: list[EvidenceItem], tool_log: list[ToolCall], chars: int
) -> list[ClaimToJudge]:
    """Cited claims whose markers all resolve to kept evidence, with their source windows."""
    by_id = {item.id: item for item in evidence}
    by_number = {c.number: by_id.get(c.evidence_id) for c in report.citations}
    result = []
    for claim in report_claims(report):
        items = [by_number.get(n) for n in claim.numbers]
        if claim.numbers and all(items):
            sources = [source_window(i, tool_log, chars) for i in items if i is not None]
            result.append(ClaimToJudge(claim.text, sources))
    return result[:MAX_CLAIMS]


# --- the judge --------------------------------------------------------------------------


@dataclass
class FaithfulnessResult:
    score: float | None  # mean of the claim scores (None: nothing to judge)
    claims: int
    details: list[ClaimScore] = field(default_factory=list)


@dataclass
class CompletenessResult:
    score: float  # computed from the aspect verdicts (see aspect_score)
    aspects: list[AspectVerdict]
    reason: str
    judge_score: int  # the judge's own overall 1-5, kept for reference


def aspect_score(verdicts: list[AspectVerdict], expected: int) -> float:
    """1-5 from the per-aspect verdicts: 1 + 4 * (yes + half of partly) / expected aspects.

    Computed, not taken from the judge: in the first real test the judge marked 2 of 3 aspects
    covered and still answered 2 (DECISIONS #102). Missing verdicts count as "no"."""
    by_aspect = {v.aspect: v.covered for v in verdicts}
    points = {"yes": 1.0, "partly": 0.5, "no": 0.0}
    covered = sum(points[by_aspect.get(n, "no")] for n in range(1, expected + 1))
    return round(1 + 4 * covered / expected, 2) if expected else 1.0


def _ask[T: BaseModel](complete: CompleteFn, system: str, user: str, model: type[T]) -> T:
    """Call the judge; an answer that isn't valid JSON for `model` is asked again once."""
    for attempt in (1, 2):
        text = complete(system, user)
        try:
            return model.model_validate(json.loads(_strip_fence(text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "judge answer unreadable", extra={"attempt": attempt, "error": str(exc)[:200]}
            )
    raise JudgeError(f"the judge did not return a valid {model.__name__}")


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def judge_faithfulness(
    complete: CompleteFn, question: str, claims: list[ClaimToJudge]
) -> FaithfulnessResult:
    if not claims:
        return FaithfulnessResult(score=None, claims=0)
    blocks = []
    for n, claim in enumerate(claims, start=1):
        sources = "\n".join(f"  SOURCE: {s}" for s in claim.sources)
        blocks.append(f"CLAIM {n}: {claim.text}\n{sources}")
    user = f"Question: {question}\n\n" + "\n\n".join(blocks)
    answer = _ask(complete, FAITHFULNESS_SYSTEM, user, FaithfulnessAnswer)
    scores = [s for s in answer.scores if 1 <= s.claim <= len(claims)]
    if not scores:
        raise JudgeError("the judge scored none of the claims")
    mean = round(sum(s.score for s in scores) / len(scores), 2)
    return FaithfulnessResult(score=mean, claims=len(claims), details=scores)


def judge_completeness(
    complete: CompleteFn, question: str, report_markdown: str, expected_aspects: list[str]
) -> CompletenessResult:
    aspects = "\n".join(f"{n}. {a}" for n, a in enumerate(expected_aspects, start=1))
    user = f"Question: {question}\n\nKey aspects:\n{aspects}\n\nReport:\n{report_markdown}"
    answer = _ask(complete, COMPLETENESS_SYSTEM, user, CompletenessAnswer)
    return CompletenessResult(
        score=aspect_score(answer.aspects, len(expected_aspects)),
        aspects=answer.aspects,
        reason=answer.reason,
        judge_score=answer.score,
    )


# --- the real model (LiteLLM -> Gemini) -------------------------------------------------


def _retryable(exc: BaseException) -> bool:
    """Rate limits, overloaded models (503), timeouts and dropped connections."""
    name = type(exc).__name__
    return name in {
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
        "Timeout",
        "APIConnectionError",
    }


def litellm_complete(settings: Settings, sleep: Callable[[float], None] = time.sleep) -> CompleteFn:
    """The judge model through LiteLLM, paced to JUDGE_REQUESTS_PER_MINUTE, with backoff."""
    import litellm

    assert settings.gemini_api_key is not None  # required by the eval entry point
    api_key = settings.gemini_api_key.get_secret_value()
    interval = 60.0 / settings.judge_requests_per_minute
    last_call = [0.0]

    def complete(system: str, user: str) -> str:
        wait = last_call[0] + interval - time.monotonic()
        if wait > 0:
            sleep(wait)
        for attempt in Retrying(
            retry=retry_if_exception(_retryable),
            wait=wait_exponential(multiplier=5, min=5, max=120),
            stop=stop_after_attempt(6),
            reraise=True,
            sleep=sleep,
        ):
            with attempt:
                last_call[0] = time.monotonic()
                response = litellm.completion(
                    model=settings.judge_model,
                    api_key=api_key,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    # No temperature: Gemini 3.5 models reject it (LiteLLM refuses the call).
                    response_format={"type": "json_object"},
                    timeout=120,
                    num_retries=0,  # the retry loop above handles it, with backoff
                )
        return str(response.choices[0].message.content or "")

    return complete
