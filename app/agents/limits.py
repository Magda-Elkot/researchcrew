"""Run sizes per depth (DECISIONS #73), sized for Groq's free tier (8K tokens/min, 200K/day).

quick: 3 sub-questions x 2 tool calls; deep: up to 5 x 4. SPEC caps a run at 25 tool calls.
"""

from dataclasses import dataclass

from app.schemas import Depth


@dataclass(frozen=True)
class DepthLimits:
    sub_questions: int  # the Planner is asked for this many (SPEC: 3-6)
    tool_calls_per_sub_question: int
    evidence_per_sub_question: int
    snippet_max_chars: int = 300


LIMITS: dict[Depth, DepthLimits] = {
    "quick": DepthLimits(
        sub_questions=3, tool_calls_per_sub_question=2, evidence_per_sub_question=3
    ),
    "deep": DepthLimits(
        sub_questions=5, tool_calls_per_sub_question=4, evidence_per_sub_question=4
    ),
}
