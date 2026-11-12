import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from minisurf.geometry import refine, triangulate, validate
from minisurf.solver import area_gradient, solve


SADDLE = np.array([[0., 0., 0.], [10., 0., 5.], [10., 10., 0.], [0., 10., 5.]])


def test_analytic_gradient_matches_finite_difference():
    vertices, faces, _ = refine(SADDLE, triangulate(SADDLE), range(4), 1)
    _, gradient = area_gradient(vertices, faces)
    def objective(z):
        trial = vertices.copy()
        trial[:, 2] = z
        return area_gradient(trial, faces)[0]
    numerical = approx_derivative(objective, vertices[:, 2]).ravel()
    np.testing.assert_allclose(gradient, numerical, atol=1e-8, rtol=1e-7)


def test_planar_solution_has_exact_area_and_fixed_boundary():
    polygon = np.array([[0., 0., 0.], [3., 0., 3.], [3., 4., 11.], [0., 4., 8.]])
    vertices, _, report = solve(polygon, levels=2)
    assert report["converged"]
    assert report["final_area"] == pytest.approx(12 * np.sqrt(6), rel=1e-12)
    np.testing.assert_array_equal(vertices[:4], polygon)
    np.testing.assert_allclose(vertices[:, 2], vertices[:, 0] + 2 * vertices[:, 1], atol=1e-10)


def test_nonplanar_refinement_reduces_area_and_converges():
    coarse, faces, r1 = solve(SADDLE, levels=2)
    fine, _, r2 = solve(SADDLE, levels=3)
    assert r1["converged"] and r2["converged"]
    assert r2["final_area"] <= r1["final_area"]
    assert r2["final_area"] < r2["initial_area"]
    np.testing.assert_array_equal(fine[:4], SADDLE)
    # All subdivided boundary points remain on the original straight 3D edges.
    incidence = {}
    for a, b, c in faces:
        for e in ((a, b), (b, c), (c, a)):
            key = tuple(sorted(e))
            incidence[key] = incidence.get(key, 0) + 1
    for i in {i for e, n in incidence.items() if n == 1 for i in e}:
        p = coarse[i]
        assert any(np.linalg.norm(np.cross(p - a, b - a)) < 1e-10
                   for a, b in zip(SADDLE, np.roll(SADDLE, -1, axis=0)))


def test_box_and_infeasible_box():
    box = [-1, -1, 0, 11, 11, 5]
    vertices, _, report = solve(SADDLE, bbox=box, levels=2)
    assert report["converged"]
    assert np.all(vertices >= np.array(box[:3])) and np.all(vertices <= np.array(box[3:]))
    with pytest.raises(ValueError, match="excludes"):
        solve(SADDLE, bbox=[0, 0, 1, 10, 10, 4])


def test_iteration_limit_not_reported_as_converged():
    _, _, report = solve(SADDLE, maxiter=1)
    assert not report["converged"]


def test_translated_scaled_boundary():
    _, _, original = solve(SADDLE, levels=2)
    moved = SADDLE * 2 + [1e8, -1e8, 1e8]
    vertices, _, report = solve(moved, levels=2)
    assert report["converged"]
    assert report["final_area"] == pytest.approx(original["final_area"] * 4, rel=1e-9)
    np.testing.assert_array_equal(vertices[:4], moved)


def test_concave_nonplanar_boundary():
    boundary = validate([[0, 0, 0], [3, 0, 1], [3, 1, 0], [1, 1, 2], [1, 3, 0], [0, 3, 1]])
    _, _, report = solve(boundary, levels=2)
    assert report["converged"]
