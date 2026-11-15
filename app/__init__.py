"""ResearchCrew application package: API, agents, tools, config and shared schemas."""

import os

__version__ = "0.1.0"

# CrewAI reads these when it is imported, so they are set here, before any app module imports
# it: no anonymous telemetry, no CrewAI-cloud tracing (DECISIONS #65). A value already in the
# environment wins.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
