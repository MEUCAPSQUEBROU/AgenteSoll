from __future__ import annotations

MESSAGE_SPLIT_MARKER = "<<SPLIT>>"


def split_agent_response(response: str) -> list[str]:
    parts = [chunk.strip() for chunk in response.split(MESSAGE_SPLIT_MARKER)]
    return [chunk for chunk in parts if chunk]
