"""PIQI Simple Assessment Module (SAM) subsystem.

Importing :mod:`sam.sams` registers the bundled SAMs with :mod:`sam.registry`.
The chain runner and registry contain no SAM-specific logic, so new SAMs are
added by dropping a new module under ``sam/sams/`` and registering it — no edits
to this subsystem's core files.
"""
