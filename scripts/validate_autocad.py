"""Live smoke test: run the venv Python with -m scripts.validate_autocad."""
from pathlib import Path
import json
import time
import uuid

import numpy as np

from minisurf.cad import AutoCAD, retry
from minisurf.solver import solve


def main():
    cad = AutoCAD()
    original = cad.doc
    test_doc = None
    destination = Path(__file__).resolve().parents[1] / "reports" / ("validation_" + uuid.uuid4().hex[:8] + ".dwg")
    destination.parent.mkdir(exist_ok=True)
    try:
        test_doc = retry(lambda: cad.app.Documents.Add())
        cad.doc = test_doc
        space = retry(lambda: test_doc.ModelSpace)
        square = np.array([[0., 0., 0.], [10., 0., 5.], [10., 10., 0.], [0., 10., 5.]])
        lines = [space.AddLine(cad.point(a), cad.point(b)) for a, b in zip(square, np.roll(square, -1, axis=0))]
        sources = [(lines, [tuple(e.StartPoint) + tuple(e.EndPoint) for e in lines])]
        poly = space.Add3DPoly(cad.point((square + [20, 0, 0]).ravel()))
        poly.Closed = True
        sources.append(([poly], tuple(poly.Coordinates)))
        light = space.AddLightWeightPolyline(cad.point([40, 0, 50, 0, 50, 10, 40, 10]))
        light.Closed = True
        light.SetBulge(0, 0.25)
        sources.append(([light], tuple(light.Coordinates)))
        arc = space.AddArc(cad.point([65, 5, 0]), 5., 0., np.pi)
        line = space.AddLine(cad.point(arc.EndPoint), cad.point(arc.StartPoint))
        sources.append(([arc, line], None))
        triangle_count = 0
        for entities, before in sources:
            boundary = cad.extract(entities)
            vertices, faces, report = solve(boundary, levels=2)
            assert report["converged"], report
            layer = cad.draw(vertices, faces)
            triangle_count += len(faces)
            if len(entities) == 4:
                assert before == [tuple(e.StartPoint) + tuple(e.EndPoint) for e in entities]
            elif len(entities) == 1:
                assert before == tuple(entities[0].Coordinates)
            print(f"{entities[0].ObjectName}: {len(faces)} triangles; area={report['final_area']:.9g}; layer={layer}")
        test_doc.SaveAs(str(destination))
        test_doc.Close(False)
        test_doc = None
        test_doc = retry(lambda: cad.app.Documents.Open(str(destination)))
        count = sum(e.ObjectName == "AcDbFace" for e in test_doc.ModelSpace)
        assert count == triangle_count, (count, triangle_count)
        print(f"PASS: saved and reopened {count} 3DFACE entities: {destination}")
        test_doc.Close(False)
        test_doc = None
        launcher = destination.parents[1] / "lisp" / "minisurf.lsp"
        if launcher.exists():
            test_doc = retry(lambda: cad.app.Documents.Add())
            for a, b in zip(square, np.roll(square, -1, axis=0)):
                retry(lambda: test_doc.ModelSpace.AddLine(cad.point(a), cad.point(b)))
            existing_reports = set(destination.parent.glob("*.json"))
            load_path = launcher.as_posix().replace('"', '\\"')
            retry(lambda: test_doc.SendCommand(f'(load "{load_path}")\nminisurf\n_all\n\n'))
            deadline = time.monotonic() + 30
            result = None
            while time.monotonic() < deadline:
                for path in set(destination.parent.glob("*.json")) - existing_reports:
                    try:
                        candidate = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if candidate.get("status") in ("drawn", "error"):
                        result = candidate
                        break
                if result is not None:
                    break
                time.sleep(0.2)
            assert result is not None, "AutoLISP launcher did not finish within 30 seconds."
            assert result["status"] == "drawn", result
            assert sum(e.ObjectName == "AcDbFace" for e in test_doc.ModelSpace) == 128
            print("PASS: AutoLISP minisurf selection -> background Python -> 128 3DFACE entities")
    finally:
        if test_doc is not None:
            try:
                retry(lambda: test_doc.Close(False))
            finally:
                retry(lambda: original.Activate())
                cad.close()
        else:
            retry(lambda: original.Activate())
            cad.close()


if __name__ == "__main__":
    main()
