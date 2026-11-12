"""Run with the virtual environment's Python; see README for setup."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback
import uuid

import numpy as np

from minisurf.solver import solve

ROOT = Path(__file__).resolve().parent


def install_lisp():
    # Pin the synced environment, avoiding PATH and working-directory assumptions in AutoCAD.
    executable = Path(sys.executable).with_name("pythonw.exe")
    if not executable.exists():
        raise ValueError("Install the AutoLISP launcher on Windows using .\\.venv\\Scripts\\python.exe main.py --install-lisp.")
    def literal(value):
        return str(value).replace("\\", "/").replace('"', '\\"')
    template = (ROOT / "lisp" / "minisurf.template.lsp").read_text(encoding="utf-8")
    output = ROOT / "lisp" / "minisurf.lsp"
    output.write_text(template.replace("@PYTHON@", literal(executable)).replace("@MAIN@", literal(ROOT / "main.py")), encoding="utf-8")
    print(f"Generated AutoLISP file: {output}")
    print("The minisurf command is not loaded into AutoCAD yet.")
    print("In the target AutoCAD drawing:")
    print("  1. Run APPLOAD.")
    print(f"  2. Select and load: {output}")
    print("  3. After 'MiniSurf loaded. Command: minisurf', run minisurf.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Minimal graph mesh for AutoCAD 2027 (ModelSpace).")
    parser.add_argument("--install-lisp", action="store_true",
                        help="Generate lisp/minisurf.lsp; load it in AutoCAD with APPLOAD")
    parser.add_argument("--document", help="Document name captured by AutoLISP")
    parser.add_argument("--handles-file", type=Path, help="One selected entity handle per line")
    parser.add_argument("--boundary-json", type=Path, help="Offline JSON array of ordered XYZ boundary vertices")
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--arc-step", type=float, default=10.0, help="Maximum arc sampling angle in degrees")
    parser.add_argument("--tolerance", type=float, default=1e-7, help="Endpoint/edge tolerance in drawing units")
    parser.add_argument("--bbox", type=float, nargs=6, metavar=("XMIN", "YMIN", "ZMIN", "XMAX", "YMAX", "ZMAX"))
    parser.add_argument("--maxiter", type=int, default=2000)
    parser.add_argument("--gtol", type=float, default=1e-6)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)
    if args.install_lisp:
        install_lisp()
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    log = args.output_dir / (run_id + ".json")
    report = {"run_id": run_id, "status": "started", "arc_step_degrees": args.arc_step,
              "endpoint_tolerance": args.tolerance}
    cad = None
    try:
        if not np.isfinite(args.tolerance) or args.tolerance <= 0:
            raise ValueError("Tolerance must be finite and positive.")
        if args.boundary_json:
            if args.handles_file or args.document:
                raise ValueError("Offline input cannot be combined with CAD document/handles.")
            boundary = np.asarray(json.loads(args.boundary_json.read_text(encoding="utf-8-sig")), dtype=float)
        else:
            from minisurf.cad import AutoCAD
            cad = AutoCAD(args.document)
            report.update(document=cad.name, autocad_version=str(cad.app.Version))
            if args.handles_file:
                handles = args.handles_file.read_text(encoding="utf-8-sig").split()
                if not handles or any(not all(c in "0123456789abcdefABCDEF" for c in h) for h in handles):
                    raise ValueError("Invalid or empty handles file.")
                entities = cad.by_handles(handles)
            else:
                entities = cad.select()
            report["source_handles"] = [str(e.Handle) for e in entities]
            boundary = cad.extract(entities, args.arc_step, args.tolerance)
            cad.prompt("Solving surface...")
        vertices, faces, result = solve(boundary, levels=args.levels, bbox=args.bbox,
                                       maxiter=args.maxiter, gtol=args.gtol, tolerance=args.tolerance)
        report.update(result)
        np.savez_compressed(args.output_dir / (run_id + ".npz"), vertices=vertices, faces=faces, boundary=boundary)
        report["mesh_file"] = run_id + ".npz"
        # Persist numerical diagnostics before any drawing mutation.
        report["status"] = "solved" if result["converged"] else "not_converged"
        log.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if not result["converged"]:
            raise RuntimeError("First-order convergence criteria not met; see report. No surface created.")
        if cad:
            report["layer"] = cad.draw(vertices, faces)
            report["status"] = "drawn"
            cad.prompt(f"Created {len(faces)} 3DFACE triangles on {report['layer']}. Report: {log}")
        print(f"Area: {result['final_area']:.12g}; report: {log}")
        return 0
    except Exception as exc:
        report.update(status="error", error=str(exc), traceback=traceback.format_exc())
        print(f"MiniSurf: {exc}\nReport: {log}", file=sys.stderr)
        if cad:
            try:
                cad.prompt(f"ERROR: {exc}. Report: {log}")
            except Exception:
                pass
        return 1
    finally:
        log.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if cad:
            cad.close()


if __name__ == "__main__":
    raise SystemExit(main())
