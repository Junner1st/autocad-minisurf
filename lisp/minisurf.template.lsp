;;; Generated launcher: .\.venv\Scripts\python.exe main.py --install-lisp
;;; Use LISPSYS=1 or 2 for Unicode project paths (restart AutoCAD after changing it).
(vl-load-com)
(defun c:minisurf (/ selection request stream index entity args started)
  (princ "\nSelect LINE/ARC entities or one closed 3DPOLY/PLINE; press Enter: ")
  (setq selection (ssget '((0 . "LINE,ARC,LWPOLYLINE,POLYLINE"))))
  (if selection
    (progn
      (setq request (vl-filename-mktemp "minisurf-" nil ".txt"))
      (setq stream (open request "w"))
      (if stream
        (progn
          (setq index 0)
          (repeat (sslength selection)
            (setq entity (ssname selection index))
            (write-line (cdr (assoc 5 (entget entity))) stream)
            (setq index (1+ index)))
          (close stream)
          (setq args (strcat "\"@MAIN@\" --document \"" (getvar "DWGNAME")
                             "\" --handles-file \"" request "\""))
          (setq started (startapp "@PYTHON@" args))
          (if started
            (princ "\nMiniSurf started. Results/errors will appear here and in the project reports folder.")
            (princ "\nMiniSurf failed to start. Regenerate the launcher with --install-lisp.")))
        (princ "\nMiniSurf cannot create its selection request file.")))
    (princ "\nMiniSurf: no selection."))
  (princ))
(princ "\nMiniSurf loaded. Command: minisurf")
(princ)
