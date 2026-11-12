import numpy as np
from scipy.optimize import minimize

from .geometry import refine, triangulate, validate


def area_gradient(vertices, faces):
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    u, w = b - a, c - a
    cross = np.cross(u, w)
    lengths = np.linalg.norm(cross, axis=1)
    if np.any(lengths <= 0):
        raise ValueError("Degenerate mesh triangle.")
    normals = cross / lengths[:, None]
    gb, gc = np.cross(w, normals)[:, 2] / 2, np.cross(normals, u)[:, 2] / 2
    gradient = np.zeros(len(vertices))
    for column, values in enumerate((-gb - gc, gb, gc)):
        np.add.at(gradient, faces[:, column], values)
    return float(lengths.sum() / 2), gradient


def solve(boundary, *, levels=3, bbox=None, maxiter=2000, gtol=1e-6, tolerance=1e-7):
    if not 1 <= levels <= 6:
        raise ValueError("Refinement levels must be between 1 and 6.")
    if maxiter < 1 or not np.isfinite(gtol) or gtol <= 0:
        raise ValueError("maxiter and gtol must be positive.")
    boundary = validate(boundary, tolerance)
    if (len(boundary) - 2) * 4**levels > 250000:
        raise ValueError("Mesh exceeds 250000 triangles; reduce refinement or arc sampling.")
    box = None if bbox is None else np.asarray(bbox, dtype=float).reshape(2, 3)
    if box is not None:
        if not np.isfinite(box).all() or np.any(box[0] > box[1]):
            raise ValueError("Invalid bounding box: expected min XYZ then max XYZ.")
        if np.any(boundary < box[0]) or np.any(boundary > box[1]):
            raise ValueError("Bounding box excludes fixed boundary vertices.")
    vertices, faces, fixed = refine(boundary, triangulate(boundary), range(len(boundary)), levels)
    free = np.setdiff1d(np.arange(len(vertices)), fixed)
    origin = vertices[0].copy()
    scale = float(np.ptp(vertices[:, :2], axis=0).max())
    work = (vertices - origin) / scale
    initial_area, _ = area_gradient(work, faces)
    bounds = None
    if box is not None:
        lo, hi = (box[:, 2] - origin[2]) / scale
        bounds = [(lo, hi)] * len(free)
    def objective(z):
        work[free, 2] = z
        area, gradient = area_gradient(work, faces)
        return area, gradient[free]
    x0 = work[free, 2].copy()
    if len(free) and not (bounds is not None and lo == hi):
        result = minimize(objective, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                          options={"maxiter": maxiter, "gtol": gtol * 0.1, "ftol": 1e-15, "maxls": 50})
        objective(result.x)
        success, message, iterations = bool(result.success), str(result.message), int(result.nit)
    else:
        success, message, iterations = True, "No unconstrained interior heights.", 0
    area, gradient = area_gradient(work, faces)
    projected = gradient[free].copy()
    if bounds is not None:
        z = work[free, 2]
        projected[(z <= lo + 1e-12) & (projected > 0)] = 0
        projected[(z >= hi - 1e-12) & (projected < 0)] = 0
    optimality = float(np.max(np.abs(projected), initial=0))
    vertices[free, 2] = work[free, 2] * scale + origin[2]
    converged = success and optimality <= gtol and area <= initial_area + 1e-12
    report = dict(converged=converged, optimizer_success=success, message=message, iterations=iterations,
                  initial_area=initial_area * scale**2, final_area=area * scale**2,
                  area_reduction=(initial_area - area) * scale**2,
                  projected_gradient_inf_normalized=optimality, optimality_tolerance=gtol,
                  boundary_error_max=0.0, vertices=len(vertices), triangles=len(faces),
                  fixed_vertices=len(fixed), refinement_levels=levels,
                  bbox=None if box is None else box.tolist(),
                  discretization_error=None,
                  method="fixed XY, piecewise linear graph, analytic Z gradient, L-BFGS-B")
    return vertices, faces, report
