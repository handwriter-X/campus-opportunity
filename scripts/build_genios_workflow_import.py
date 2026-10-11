"""Backward-compatible entry point for the native NK-GeniOS workflow generator.

Use ``scripts/create_genios_workflow.py`` for new invocations. This wrapper is
kept so existing notes and commands continue to produce the upload-verified
native export shape.
"""

from create_genios_workflow import main


if __name__ == "__main__":
    raise SystemExit(main())
