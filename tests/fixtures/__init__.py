"""Synthetic fixtures shared by the audit-round-4e test modules.

Nothing in this package is copied from the operator's data. The bake-off
pipeline reads private session transcripts and the memory store reads a
private corpus; this is a PUBLIC repository, so every name, date, tag, and
sentence below is invented. The *shapes* were read from the writers —
``scripts/resample-bake-off-manifest.py:write_manifest`` for a manifest row,
``scripts/analyse-wiki-vocabulary.py:load_memories`` for a memory record —
and then re-populated with fictional archaeology.
"""
