"""Channel graph — corridor network between grid objects."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .params import GridConfig


@dataclass
class ChannelGraph:
    """Navigable corridor network between grid objects.

    Nodes sit at the centres of interstitial cells (the spaces between
    objects).  Edges connect adjacent cells through the gaps.
    """

    nodes: list[tuple[float, float]]
    adj: list[list[int]]  # adj[i] = indices of neighbours of node i


def _build_channel_graph_regular(
    rows: int,
    cols: int,
    spacing: float,
    x0: float,
    y0: float,
) -> ChannelGraph:
    """Dual grid for a non-offset rectangular lattice.

    Each rectangular cell formed by four neighbouring objects becomes a
    node at its centre.  Adjacent cells (sharing a side) are connected.
    """
    nodes: list[tuple[float, float]] = []
    idx: dict[tuple[int, int], int] = {}

    for r in range(rows - 1):
        for c in range(cols - 1):
            idx[(r, c)] = len(nodes)
            nodes.append((x0 + (c + 0.5) * spacing, y0 + (r + 0.5) * spacing))

    adj: list[list[int]] = [[] for _ in range(len(nodes))]
    for (r, c), i in idx.items():
        for dr, dc in [(0, 1), (1, 0)]:
            nb = (r + dr, c + dc)
            if nb in idx:
                j = idx[nb]
                adj[i].append(j)
                adj[j].append(i)

    return ChannelGraph(nodes, adj)


def _build_channel_graph_offset(
    rows: int,
    cols: int,
    spacing: float,
    x0: float,
    y0: float,
) -> ChannelGraph:
    """Dual graph for a brick-stagger (offset rows) lattice.

    Between each pair of consecutive rows the stagger creates triangular
    cells.  Each triangle becomes a node at its centroid; triangles sharing
    an edge of the triangulation are adjacent in the channel graph.
    """
    s = spacing
    nodes: list[tuple[float, float]] = []

    # Map each edge of the object triangulation (pair of object ids) to
    # the triangle indices that border it.  Two triangles sharing an edge
    # are adjacent corridor junctions.
    edge_to_tris: dict[frozenset[int], list[int]] = {}

    def obj_id(r: int, c: int) -> int:
        return r * cols + c

    def add_triangle(verts: list[tuple[int, int]], centroid: tuple[float, float]) -> None:
        tri_idx = len(nodes)
        nodes.append(centroid)
        ids = [obj_id(r, c) for r, c in verts]
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                edge = frozenset((ids[a], ids[b]))
                edge_to_tris.setdefault(edge, []).append(tri_idx)

    for r in range(rows - 1):
        yr = y0 + r * s
        if r % 2 == 0:
            # Even -> odd transition.
            # "Up" triangles: (r,c), (r,c+1), (r+1,c)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r, c + 1), (r + 1, c)],
                    (x0 + c * s + s / 2, yr + s / 3),
                )
            # "Down" triangles: (r,c), (r+1,c-1), (r+1,c)
            for c in range(1, cols):
                add_triangle(
                    [(r, c), (r + 1, c - 1), (r + 1, c)],
                    (x0 + c * s, yr + 2 * s / 3),
                )
        else:
            # Odd -> even transition.
            # Type A: (r,c), (r+1,c), (r+1,c+1)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r + 1, c), (r + 1, c + 1)],
                    (x0 + c * s + s / 2, yr + 2 * s / 3),
                )
            # Type B: (r,c), (r,c+1), (r+1,c+1)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r, c + 1), (r + 1, c + 1)],
                    (x0 + (c + 1) * s, yr + s / 3),
                )

    adj: list[list[int]] = [[] for _ in range(len(nodes))]
    for tris in edge_to_tris.values():
        for a in range(len(tris)):
            for b in range(a + 1, len(tris)):
                adj[tris[a]].append(tris[b])
                adj[tris[b]].append(tris[a])

    return ChannelGraph(nodes, adj)


def build_channel_graph(cfg: GridConfig) -> ChannelGraph:
    """Build the corridor junction graph for a grid configuration.

    The graph represents the navigable interstitial space between grid
    objects.  Lights using the ``"channel"`` path style walk this graph.

    NOTE: the graph is built from the full grid before hole removal.
    Holes could open shortcuts through the corridor network — this is
    a consideration for future experimentation.
    """
    if cfg.rows < 2 or cfg.cols < 2:
        return ChannelGraph([], [])
    grid_w = (cfg.cols - 1) * cfg.spacing
    grid_h = (cfg.rows - 1) * cfg.spacing
    x0 = -grid_w / 2
    y0 = -grid_h / 2
    if cfg.offset_rows:
        return _build_channel_graph_offset(cfg.rows, cfg.cols, cfg.spacing, x0, y0)
    return _build_channel_graph_regular(cfg.rows, cfg.cols, cfg.spacing, x0, y0)


def _shortest_path(graph: ChannelGraph, start: int, end: int) -> list[int]:
    """Dijkstra shortest path on the channel graph.  Returns node indices."""
    n = len(graph.nodes)
    dist = [float("inf")] * n
    prev = [-1] * n
    dist[start] = 0.0
    heap: list[tuple[float, int]] = [(0.0, start)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        if u == end:
            break
        for v in graph.adj[u]:
            dx = graph.nodes[v][0] - graph.nodes[u][0]
            dy = graph.nodes[v][1] - graph.nodes[u][1]
            nd = d + math.hypot(dx, dy)
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    path: list[int] = []
    u = end
    while u != -1:
        path.append(u)
        u = prev[u]
    path.reverse()
    return path if path and path[0] == start else [start]
