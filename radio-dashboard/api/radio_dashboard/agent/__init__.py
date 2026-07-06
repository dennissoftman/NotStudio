"""LLM agent surface for the Radio Dashboard.

Exposes the station's job-management API to an LLM "radio agent": machine-readable
tool schemas (Anthropic + OpenAI JSON), a system prompt, a live state snapshot,
and an in-process executor that maps a tool call onto the REST API. The React UI
remains the human dashboard / manual-override surface.
"""

from .prompts import RADIO_AGENT_SYSTEM_PROMPT, render_system_prompt  # noqa: F401
from .tools import (  # noqa: F401
    TOOL_BY_NAME,
    TOOLS,
    anthropic_tools,
    gemini_tools,
    openai_tools,
)
