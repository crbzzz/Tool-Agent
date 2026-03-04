"""Dependency wiring for FastAPI."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv

from rag.agent.mistral_client import MistralAgentsClient
from rag.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_orchestrator() -> AgentOrchestrator:
    """Create a singleton orchestrator configured from environment variables."""

    load_dotenv(find_dotenv(".env"), override=False)
    api_key = os.environ.get("MISTRAL_API_KEY")
    agent_id = os.environ.get("MISTRAL_AGENT_ID")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set")
    if not agent_id:
        raise RuntimeError("MISTRAL_AGENT_ID is not set")

    client = MistralAgentsClient(api_key=api_key)
    return AgentOrchestrator(mistral_client=client, agent_id=agent_id)
