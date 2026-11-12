"""AutoCAD ActiveX adapter. Imports pywin32 only when connecting."""
import math
import time
import uuid

import numpy as np

from .geometry import assemble


def retry(action):
    import pywintypes
    for attempt in range(50):
        try:
            return action()
        except pywintypes.com_error as exc:
            if exc.hresult not in (-2147418111, -2147417846) or attempt == 49:
                raise
            time.sleep(0.2)
        except AttributeError:
            # pywin32 dynamic dispatch can hide a rejected GetIDsOfNames call
            # as AttributeError while AutoCAD is opening/closing a document.
            if attempt == 49:
                raise
            time.sleep(0.2)


class AutoCAD:
    def __init__(self, document=None):
        import pythoncom
        import win32com.client
        self.pythoncom = pythoncom
        self.client = win32com.client
        pythoncom.CoInitialize()
        try:
            self.app = win32com.client.GetActiveObject("AutoCAD.Application")
            self.doc = retry(lambda: self.app.ActiveDocument if document is None else self.app.Documents.Item(document))
            # Bind this document once; subsequent operations never follow active-document changes.
            self.name = retry(lambda: self.doc.Name)
        except Exception:
            pythoncom.CoUninitialize()
            raise

    def close(self):
        self.pythoncom.CoUninitialize()

    def point(self, p):
        return self.client.VARIANT(self.pythoncom.VT_ARRAY | self.pythoncom.VT_R8, tuple(map(float, p)))

    def prompt(self, text):
        retry(lambda: self.doc.Utility.Prompt("\nMiniSurf: " + text + "\n"))

    def select(self):
        selection = retry(lambda: self.doc.SelectionSets.Add("MINISURF_" + uuid.uuid4().hex))
        try:
            self.prompt("Select LINE/ARC or one closed 3DPOLY/PLINE, then Enter.")
            selection.SelectOnScreen()
            return [selection.Item(i) for i in range(selection.Count)]
        finally:
            retry(selection.Delete)

    def by_handles(self, handles):
        return [retry(lambda h=h: self.doc.HandleToObject(h)) for h in handles]

    def wcs(self, point, normal, displacement=False):
        return np.asarray(self.doc.Utility.TranslateCoordinates(self.point(point), 4, 0, displacement,
                                                               self.point(normal)), dtype=float)

    def extract(self, entities, arc_step_degrees=10.0, tolerance=1e-7):
        if not 0.1 <= arc_step_degrees <= 90:
            raise ValueError("Arc sampling step must be between 0.1 and 90 degrees.")
        if not entities:
            raise ValueError("No objects selected.")
        names = [e.ObjectName for e in entities]
        polytypes = {"AcDb3dPolyline", "AcDbPolyline", "AcDb2dPolyline"}
        if any(n in polytypes for n in names) and len(entities) != 1:
            raise ValueError("Select exactly one closed polyline, or a set of LINE/ARC entities.")
        paths = []
        step = math.radians(arc_step_degrees)
        for e, name in zip(entities, names):
            if e.OwnerID != self.doc.ModelSpace.ObjectID:
                raise ValueError("Boundary entities must belong to ModelSpace.")
            if name == "AcDbLine":
                paths.append(np.asarray([e.StartPoint, e.EndPoint]))
            elif name == "AcDbArc":
                start, end = float(e.StartAngle), float(e.EndAngle)
                sweep = (end - start) % (2 * math.pi)
                count = max(1, math.ceil(sweep / step))
                center = np.asarray(e.Center)
                points = [center + self.wcs((e.Radius * math.cos(t), e.Radius * math.sin(t), 0), e.Normal, True)
                          for t in np.linspace(start, start + sweep, count + 1)]
                points[0], points[-1] = np.asarray(e.StartPoint), np.asarray(e.EndPoint)
                paths.append(points)
            elif name in polytypes:
                if not e.Closed:
                    raise ValueError("Polyline must be closed (Closed=True).")
                coordinates = np.asarray(e.Coordinates, dtype=float)
                if name == "AcDb3dPolyline":
                    if e.Type != 0:
                        raise ValueError("Fitted/spline 3DPOLY is unsupported; use a simple 3DPOLY.")
                    points = coordinates.reshape(-1, 3)
                    paths.append(np.vstack((points, points[0])))
                else:
                    if name == "AcDb2dPolyline" and e.Type != 0:
                        raise ValueError("Fitted/spline PLINE is unsupported.")
                    xy = coordinates.reshape(-1, 2) if name == "AcDbPolyline" else coordinates.reshape(-1, 3)[:, :2]
                    sampled = []
                    for i, a in enumerate(xy):
                        b = xy[(i + 1) % len(xy)]
                        bulge = float(e.GetBulge(i))
                        if not np.isfinite(bulge):
                            raise ValueError("Invalid PLINE bulge.")
                        if abs(bulge) < 1e-14:
                            segment = [a]
                        else:
                            chord = b - a
                            if np.linalg.norm(chord) <= tolerance:
                                raise ValueError("Zero length PLINE arc chord.")
                            center = (a + b) / 2 + np.array([-chord[1], chord[0]]) * (1 - bulge**2) / (4 * bulge)
                            sweep = 4 * math.atan(bulge)
                            angle = math.atan2(*(a - center)[::-1])
                            count = max(1, math.ceil(abs(sweep) / step))
                            radius = np.linalg.norm(a - center)
                            segment = [a] + [center + radius * np.array([math.cos(t), math.sin(t)])
                                             for t in np.linspace(angle, angle + sweep, count + 1)[1:-1]]
                        sampled.extend(self.wcs((*p, e.Elevation), e.Normal) for p in segment)
                    paths.append(np.vstack((sampled, sampled[0])))
            else:
                raise ValueError(f"Unsupported entity: {name}; select LINE, ARC or a closed polyline.")
        return assemble(paths, tolerance)

    def draw(self, vertices, faces):
        layer_name = "MINISURF_" + uuid.uuid4().hex[:12]
        created, layer = [], None
        retry(self.doc.StartUndoMark)
        try:
            layer = retry(lambda: self.doc.Layers.Add(layer_name))
            layer.Color = 3
            for a, b, c in faces:
                p, q, r = (self.point(vertices[i]) for i in (a, b, c))
                face = retry(lambda: self.doc.ModelSpace.Add3DFace(p, q, r, r))
                created.append(face)
                retry(lambda: setattr(face, "Layer", layer_name))
            retry(lambda: self.doc.Regen(1))
        except Exception as exc:
            failures = []
            for face in reversed(created):
                try:
                    retry(face.Delete)
                except Exception as cleanup_error:
                    failures.append(str(cleanup_error))
            if layer is not None and not failures:
                try:
                    retry(layer.Delete)
                except Exception as cleanup_error:
                    failures.append(str(cleanup_error))
            if failures:
                raise RuntimeError(f"Drawing failed; cleanup incomplete on layer {layer_name}: {failures}") from exc
            raise
        finally:
            retry(self.doc.EndUndoMark)
        return layer_name
