"""Procedural network maps for Hacker Collective floors."""

from __future__ import annotations

import random
from typing import Any

NODE_KINDS: dict[str, tuple[str, str]] = {
    "firewall": ("FW", "grit"),
    "database": ("DB", "nouse"),
    "mail": ("MX", "charm"),
    "maintenance": ("MT", "care"),
    "legacy": ("LG", "chaos"),
}

DEFAULT_NODE_COUNT = 10
MIN_NODE_COUNT = 5
MAX_NODE_COUNT = 12
ENTRY_ENTROPY = 0

KIND_NAMES: dict[str, str] = {
    "firewall": "FIREWALL",
    "database": "DATA VAULT",
    "mail": "MAIL RELAY",
    "maintenance": "MAINT BOT",
    "legacy": "LEGACY BOX",
}


def layer_sizes(node_count: int) -> list[int]:
    """Split a node count into two-wide layers, with a lone tail when needed."""

    if not MIN_NODE_COUNT <= node_count <= MAX_NODE_COUNT:
        raise ValueError(f"Network maps support {MIN_NODE_COUNT}-{MAX_NODE_COUNT} nodes.")
    sizes: list[int] = []
    remaining = node_count
    while remaining > 0:
        take = 2 if remaining >= 2 else 1
        sizes.append(take)
        remaining -= take
    return sizes


def _kind_order(rng: random.Random, node_count: int) -> list[str]:
    kinds = list(NODE_KINDS)
    order: list[str] = []
    while len(order) < node_count:
        batch = kinds * 2
        rng.shuffle(batch)
        order.extend(batch)
    return order[:node_count]


def generate_map(seed: str, node_count: int = DEFAULT_NODE_COUNT) -> dict[str, Any]:
    """Build a seeded dependency graph and its layout."""

    sizes = layer_sizes(node_count)
    rng = random.Random(f"tinytown-hacker-map:{seed}:{node_count}")
    kinds = _kind_order(rng, node_count)
    layers: list[list[str]] = []
    nodes: dict[str, dict[str, Any]] = {}
    index = 0
    for layer in range(len(sizes)):
        row: list[str] = []
        for _ in range(sizes[layer]):
            node_id = f"n{index + 1}"
            kind = kinds[index]
            code, approach = NODE_KINDS[kind]
            row.append(node_id)
            nodes[node_id] = {
                "id": node_id,
                "label": f"{code}-{index + 1:02d}",
                "name": KIND_NAMES[kind],
                "kind": kind,
                "approach": approach,
                "layer": layer,
                "depends_on": [],
                "x": 0.0,
                "y": 0.5,
            }
            index += 1
        layers.append(row)
    for layer in range(1, len(layers)):
        parents = layers[layer - 1]
        for position, node_id in enumerate(layers[layer]):
            primary = parents[position % len(parents)]
            deps = [primary]
            if len(parents) > 1 and rng.random() < 0.4:
                extra = rng.choice([parent for parent in parents if parent != primary])
                deps.append(extra)
            nodes[node_id]["depends_on"] = sorted(set(deps))
    for layer_index, layer in enumerate(layers):
        for position, node_id in enumerate(layer):
            span = 0.72 if len(layer) > 1 else 0.0
            sway = (position - (len(layer) - 1) / 2) * span
            jitter = rng.uniform(-0.05, 0.05)
            nodes[node_id]["y"] = round(min(0.88, max(0.12, 0.5 + sway + jitter)), 3)
            if len(layers) == 1:
                nodes[node_id]["x"] = 0.5
            else:
                nodes[node_id]["x"] = round(0.10 + layer_index * (0.76 / (len(layers) - 1)), 3)
    edges = [
        {"from": parent, "to": node["id"]}
        for node in nodes.values()
        for parent in node["depends_on"]
    ]
    central = {
        "id": "central",
        "label": "CORE",
        "name": "CENTRAL SERVER",
        "kind": "core",
        "approach": "nouse",
        "layer": len(layers),
        "depends_on": list(nodes),
        "x": 1.0,
        "y": 0.5,
    }
    edges.extend({"from": node_id, "to": "central"} for node_id in nodes)
    order = sorted(nodes)
    return {
        "seed": seed,
        "node_count": node_count,
        "nodes": [nodes[node_id] for node_id in order],
        "central": central,
        "edges": edges,
        "entry_ids": list(layers[0]),
    }


def available_ids(cleared: list[str], generated: dict[str, Any]) -> list[str]:
    """Return the nodes whose dependencies are all cleared."""

    done = set(cleared)
    return [
        node["id"]
        for node in generated["nodes"]
        if node["id"] not in done and set(node["depends_on"]).issubset(done)
    ]


def central_available(cleared: list[str], generated: dict[str, Any]) -> bool:
    return set(generated["central"]["depends_on"]).issubset(set(cleared))
