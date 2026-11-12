from types import SimpleNamespace

import numpy as np
import pytest

from minisurf.cad import AutoCAD


def adapter():
    cad = AutoCAD.__new__(AutoCAD)
    cad.doc = SimpleNamespace(ModelSpace=SimpleNamespace(ObjectID=10))
    cad.wcs = lambda p, normal, displacement=False: np.asarray(p, dtype=float)
    return cad


def test_closed_3dpoly_and_invalid_mixed_selection():
    poly = SimpleNamespace(ObjectName="AcDb3dPolyline", OwnerID=10, Closed=True, Type=0,
                           Coordinates=[0, 0, 0, 2, 0, 1, 2, 2, 0, 0, 2, 1])
    cad = adapter()
    assert cad.extract([poly]).shape == (4, 3)
    with pytest.raises(ValueError, match="exactly one"):
        cad.extract([poly, poly])


def test_arc_and_line_form_semicircle():
    arc = SimpleNamespace(ObjectName="AcDbArc", OwnerID=10, StartAngle=0., EndAngle=np.pi,
                          Radius=2., Center=[0, 0, 0], Normal=[0, 0, 1],
                          StartPoint=[2, 0, 0], EndPoint=[-2, 0, 0])
    line = SimpleNamespace(ObjectName="AcDbLine", OwnerID=10, StartPoint=[-2, 0, 0], EndPoint=[2, 0, 0])
    points = adapter().extract([line, arc], arc_step_degrees=30)
    assert len(points) == 7
    assert np.min(points[:, 1]) >= 0
    np.testing.assert_allclose(np.linalg.norm(points[:, :2], axis=1), 2.)


@pytest.mark.parametrize("bulge", [1., -1.])
def test_lwpolyline_bulge_sampling(bulge):
    poly = SimpleNamespace(ObjectName="AcDbPolyline", OwnerID=10, Closed=True,
                           Coordinates=[-2, 0, 2, 0], Normal=[0, 0, 1], Elevation=3.,
                           GetBulge=lambda i: bulge if i == 0 else 0.)
    points = adapter().extract([poly], arc_step_degrees=30)
    assert len(points) == 7
    np.testing.assert_allclose(points[:, 2], 3.)
    np.testing.assert_allclose(np.linalg.norm(points[:, :2], axis=1), 2.)


def test_drawing_rolls_back_created_faces_on_failure():
    calls = []
    class Layer:
        def Delete(self):
            calls.append("delete_layer")
    class Face:
        def Delete(self):
            calls.append("delete_face")
    class Space:
        def Add3DFace(self, *args):
            calls.append("add")
            if calls.count("add") == 2:
                raise RuntimeError("synthetic write failure")
            return Face()
    cad = adapter()
    cad.point = lambda p: p
    cad.doc = SimpleNamespace(ModelSpace=Space(), Layers=SimpleNamespace(Add=lambda name: Layer()),
                              StartUndoMark=lambda: calls.append("start"),
                              EndUndoMark=lambda: calls.append("end"))
    with pytest.raises(RuntimeError, match="synthetic"):
        cad.draw(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]), np.array([[0, 1, 2], [0, 1, 2]]))
    assert calls == ["start", "add", "add", "delete_face", "delete_layer", "end"]
