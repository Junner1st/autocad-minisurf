"""Boundary reconstruction and polygon triangulation; no CAD dependencies."""
import math

import gmpy2
import numpy as np


def orient(a, b, c):
    u, v = b - a, c - a
    d = float(u[0] * v[1] - u[1] * v[0])
    if abs(d) > 1e-14 * (abs(u[0] * v[1]) + abs(u[1] * v[0])):
        return d
    # Exact rational fallback for nearly collinear binary floating-point inputs.
    ax, ay, bx, by, cx, cy = map(gmpy2.mpq, map(float, (*a, *b, *c)))
    exact = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return float(gmpy2.sign(exact)) * np.finfo(float).tiny


def assemble(paths, tolerance=1e-7):
    """Join sampled open paths into exactly one degree-two closed loop."""
    if not paths:
        raise ValueError("No boundary entities selected.")
    nodes, edges, adjacency = [], [], []

    def node(p):
        matches = [i for i, q in enumerate(nodes) if np.linalg.norm(p - q) <= tolerance]
        if len(matches) > 1:
            raise ValueError("Ambiguous endpoint matching; reduce tolerance.")
        if matches:
            return matches[0]
        nodes.append(p.copy())
        adjacency.append([])
        return len(nodes) - 1

    for path in paths:
        p = np.asarray(path, dtype=float)
        if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2 or not np.isfinite(p).all():
            raise ValueError("Invalid boundary coordinates.")
        a, b = node(p[0]), node(p[-1])
        idx = len(edges)
        edges.append((a, b, p))
        adjacency[a].append(idx)
        adjacency[b].append(idx)
    if any(len(e) != 2 for e in adjacency):
        raise ValueError("Boundary is open, branched, duplicated, or endpoints do not match.")
    result, used, current = [], set(), 0
    while len(used) < len(edges):
        choices = [e for e in adjacency[current] if e not in used]
        if not choices:
            raise ValueError("Multiple disconnected closed boundaries selected.")
        idx = choices[0]
        a, b, p = edges[idx]
        if a != current:
            p = p[::-1]
        # Snap only matched junctions; preserve the intermediate sampled curve.
        p = p.copy()
        p[0], p[-1] = nodes[current], nodes[b if a == current else a]
        result.extend(p[:-1])
        current = b if a == current else a
        used.add(idx)
    if current != 0:
        raise ValueError("Boundary is not closed.")
    return validate(np.asarray(result), tolerance)


def validate(vertices, tolerance=1e-7):
    v = np.asarray(vertices, dtype=float)
    if v.ndim != 2 or v.shape[1] != 3 or len(v) < 3 or not np.isfinite(v).all():
        raise ValueError("Boundary requires at least three finite XYZ points.")
    span = float(np.ptp(v[:, :2], axis=0).max())
    if span <= tolerance:
        raise ValueError("XY projection is degenerate.")
    p = (v[:, :2] - v[0, :2]) / span
    eps = tolerance / span
    for i in range(len(p)):
        if np.linalg.norm(p[i] - p[(i + 1) % len(p)]) <= eps:
            raise ValueError("Zero length XY edge or vertical boundary segment.")
    def on(a, b, c):
        return orient(a, b, c) == 0 and np.all(c >= np.minimum(a, b)) and np.all(c <= np.maximum(a, b))
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        c = p[(i + 2) % len(p)]
        if orient(a, b, c) == 0 and np.dot(a - b, c - b) > 0:
            raise ValueError("Adjacent boundary edges overlap in XY.")
        for j in range(i + 2, len(p)):
            if i == 0 and j == len(p) - 1:
                continue
            c, d = p[j], p[(j + 1) % len(p)]
            s = [orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)]
            if ((np.sign(s[0]) * np.sign(s[1]) < 0 and np.sign(s[2]) * np.sign(s[3]) < 0)
                    or on(a, b, c) or on(a, b, d) or on(c, d, a) or on(c, d, b)):
                raise ValueError("XY boundary self-intersects or touches itself.")
    area2 = math.fsum(float(p[i, 0] * p[(i + 1) % len(p), 1] -
                            p[i, 1] * p[(i + 1) % len(p), 0]) for i in range(len(p)))
    if abs(area2) <= eps * eps:
        raise ValueError("XY polygon has zero area.")
    return v.copy() if area2 > 0 else v[::-1].copy()


def triangulate(vertices):
    p = vertices[:, :2]
    p = (p - p[0]) / np.ptp(p, axis=0).max()
    remaining, faces = list(range(len(p))), []
    while len(remaining) > 3:
        for k, b in enumerate(remaining):
            a, c = remaining[k - 1], remaining[(k + 1) % len(remaining)]
            if orient(p[a], p[b], p[c]) <= 0:
                continue
            if any(all(orient(p[u], p[w], p[q]) >= 0 for u, w in ((a, b), (b, c), (c, a)))
                   for q in remaining if q not in (a, b, c)):
                continue
            faces.append((a, b, c))
            remaining.pop(k)
            break
        else:
            raise ValueError("Cannot triangulate boundary; check collinear or duplicate vertices.")
    if orient(*(p[i] for i in remaining)) <= 0:
        raise ValueError("Degenerate final triangle.")
    faces.append(tuple(remaining))
    return np.asarray(faces, dtype=int)


def refine(vertices, faces, boundary, levels):
    v = [p.copy() for p in vertices]
    fixed = set(boundary)
    boundary_edges = {tuple(sorted((i, (i + 1) % len(vertices)))) for i in range(len(vertices))}
    for _ in range(levels):
        midpoints, new_edges, new_faces = {}, set(), []
        def midpoint(a, b):
            edge = tuple(sorted((int(a), int(b))))
            if edge not in midpoints:
                m = len(v)
                v.append((v[a] + v[b]) / 2)
                midpoints[edge] = m
                if edge in boundary_edges:
                    fixed.add(m)
                    new_edges.update((tuple(sorted((a, m))), tuple(sorted((m, b)))))
            return midpoints[edge]
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            new_faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        faces, boundary_edges = np.asarray(new_faces, dtype=int), new_edges
    return np.asarray(v), faces, np.asarray(sorted(fixed), dtype=int)
