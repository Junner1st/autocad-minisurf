import numpy as np
import pytest

from minisurf.geometry import assemble, refine, triangulate, validate


SQUARE = np.array([[0., 0., 0.], [4., 0., 1.], [4., 4., 0.], [0., 4., 1.]])


def test_unordered_reversed_lines():
    paths = [SQUARE[[2, 1]], SQUARE[[0, 3]], SQUARE[[1, 0]], SQUARE[[3, 2]]]
    result = assemble(paths)
    assert {tuple(p) for p in result} == {tuple(p) for p in SQUARE}


def test_single_closed_sampled_path():
    np.testing.assert_array_equal(assemble([np.vstack((SQUARE, SQUARE[0]))]), SQUARE)


@pytest.mark.parametrize("paths, message", [
    ([SQUARE[[0, 1]], SQUARE[[1, 2]]], "open"),
    ([np.vstack((SQUARE, SQUARE[0])), np.vstack((SQUARE + 10, SQUARE[0] + 10))], "disconnected"),
    ([SQUARE[[0, 1]], SQUARE[[1, 2]], SQUARE[[2, 3]], SQUARE[[3, 0]], SQUARE[[0, 1]]], "branched"),
])
def test_invalid_topology(paths, message):
    with pytest.raises(ValueError, match=message):
        assemble(paths)


@pytest.mark.parametrize("points, message", [
    ([[0, 0, 0], [3, 3, 0], [0, 3, 1], [3, 0, 0]], "self-intersects"),
    ([[0, 0, 0], [0, 0, 1], [2, 0, 0], [0, 2, 0]], "vertical"),
    ([[0, 0, 0], [3, 0, 0], [1, 0, 0], [0, 2, 0]], "overlap"),
    ([[0, 0, 0], [3, 0, 0], [3, 3, 0], [1, 0, 1], [0, 3, 0]], "touches"),
])
def test_invalid_projection(points, message):
    with pytest.raises(ValueError, match=message):
        validate(points)


def test_concave_mesh_preserves_domain_and_manifold():
    polygon = validate([[0, 0, 0], [3, 0, 1], [3, 1, 0], [1, 1, 2], [1, 3, 0], [0, 3, 1]])
    vertices, faces, fixed = refine(polygon, triangulate(polygon), range(len(polygon)), 2)
    triangles = vertices[faces, :2]
    u, v = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    assert np.sum(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) / 2 == pytest.approx(5)
    counts = {}
    for a, b, c in faces:
        for edge in ((a, b), (b, c), (c, a)):
            key = tuple(sorted(edge))
            counts[key] = counts.get(key, 0) + 1
    assert all(n in (1, 2) for n in counts.values())
    boundary_nodes = {i for edge, n in counts.items() if n == 1 for i in edge}
    assert boundary_nodes == set(fixed)
    assert len(vertices) - len(counts) + len(faces) == 1


def test_collinear_boundary_points_retained():
    polygon = validate([[0, 0, 0], [1, 0, 2], [2, 0, 0], [2, 2, 0], [0, 2, 0]])
    faces = triangulate(polygon)
    assert set(faces.flat) == set(range(5))
