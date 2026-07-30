"""Pytest collection configuration.

The ``bug_examples`` scripts and the ``test_hook_*`` files are runnable demos /
repro fixtures (``__main__`` guarded, no assertions), not automated tests. They
are excluded from collection so ``pytest`` reports only real test outcomes.
"""

collect_ignore_glob = [
    "test_hook_*.py",
    "bug_examples/*",
]
