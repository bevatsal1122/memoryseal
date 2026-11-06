"""Bounded memory scans for the live demo's observations."""


def find_readable_memory(client, agent_id: str, namespace: str, memory_id: str) -> list[dict]:
    """Scan bounded pages without treating an incomplete scan as absence."""
    matches = []
    offset = 0
    for _ in range(50):
        page = client.read_memory_page(agent_id, namespace, offset=offset, limit=100)
        matches.extend(item for item in page["memories"] if item.get("id") == memory_id)
        if len(matches) >= 2:
            return matches[:2]
        if page["next_offset"] is None:
            return matches
        offset = page["next_offset"]
    raise ValueError("Memory scan exceeded the demo page limit")
