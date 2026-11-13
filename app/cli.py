"""Command-line entry point (`researchcrew "question"`). A stub until Phase 3."""

from app.config import require
from app.log import get_logger

logger = get_logger(__name__)

# Keys the CLI needs at startup. Empty in Phase 1; Phase 3 adds "GROQ_API_KEY".
REQUIRED_KEYS: tuple[str, ...] = ()


def main() -> int:
    """Run the CLI and return the process exit code."""
    require(*REQUIRED_KEYS)
    logger.info("researchcrew CLI is available in Phase 3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
