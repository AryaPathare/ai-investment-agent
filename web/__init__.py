"""HTTP front end for the pipeline.

Deliberately empty. `web.app` imports agent code, and importing THIS package
must stay free of that - the same rule `workflow.py` and `checkpoints.py`
already follow, for the same reason: a module that reads settings or opens a
database merely because something imported it breaks every path that was
supposed to work without configuration.
"""
