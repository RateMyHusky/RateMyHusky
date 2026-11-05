"""Prune safety ceiling — pure function, no DB."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from load_evidence import check_prune, PRUNE_CEILING  # noqa: E402


def test_prune_refuses_when_build_returned_nothing():
    with pytest.raises(SystemExit, match="reddit"):
        check_prune("reddit", n_db=8789, n_fresh=0, n_stale=8789, force=True)


def test_prune_refuses_over_ceiling_without_force():
    with pytest.raises(SystemExit, match="rmp"):
        check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=False)


def test_prune_allows_over_ceiling_with_force():
    check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=True)


def test_prune_allows_normal_week():
    check_prune("rmp", n_db=41392, n_fresh=44900, n_stale=14, force=False)


def test_ceiling_value():
    assert PRUNE_CEILING == 0.05
