from __future__ import annotations
import json
from pigeon_poker.preflop_gto_strategy import _data

data = _data()
print("RANGE_SOURCE_NODE_COUNT", len(data.get("nodes", [])))
for index, node in enumerate(data.get("nodes", []), 1):
    print("RANGE_SOURCE_NODE", json.dumps({
        "index": index,
        "node_id": node.get("id"),
        "source_image": node.get("source_image"),
        "description": node.get("description"),
        "action_totals": node.get("action_totals"),
        "active_range": node.get("active_range"),
        "hand_classes": len(node.get("hands", {})),
    }, ensure_ascii=False, separators=(",", ":")))
