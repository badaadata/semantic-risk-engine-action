import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.post_comment import (
    MARKER,
    _build_downstream_map,
    find_existing_comment,
    format_comment,
)

EMPTY_MANIFEST = {"metadata": {"project_name": "my_project"}, "nodes": {}, "child_map": {}}


def _make_response(results=None, models_with_high_risk=0):
    return {
        "request_id": "test-uuid",
        "dialect": "snowflake",
        "total_models": len(results or []),
        "models_with_high_risk": models_with_high_risk,
        "results": results or [],
    }


def test_format_no_changes():
    response = _make_response(results=[], models_with_high_risk=0)
    comment = format_comment(response, EMPTY_MANIFEST)
    assert MARKER in comment
    assert "no" in comment.lower() or "no sql" in comment.lower()


def test_format_high_risk():
    high_item = {
        "entity": "FILTER",
        "change_type": "REMOVED",
        "identifier": "WHERE:status",
        "severity": "HIGH",
        "reason": "A WHERE filter was removed. Queries may return more rows than expected.",
        "old_value": "status = 'active'",
        "new_value": None,
    }
    response = _make_response(
        results=[
            {
                "model_name": "fct_revenue",
                "has_error": False,
                "error_message": None,
                "high": [high_item],
                "medium": [],
                "low": [],
                "info": [],
            }
        ],
        models_with_high_risk=1,
    )
    comment = format_comment(response, EMPTY_MANIFEST)

    assert MARKER in comment
    assert "fct_revenue" in comment
    assert "❌ 1" in comment
    assert "WHERE:status" in comment
    assert "HIGH risk" in comment


def test_format_compile_error():
    response = _make_response(
        results=[
            {
                "model_name": "broken_model",
                "has_error": True,
                "error_message": "Compilation error: unknown relation",
                "high": [],
                "medium": [],
                "low": [],
                "info": [],
            }
        ],
        models_with_high_risk=0,
    )
    comment = format_comment(response, EMPTY_MANIFEST)
    assert "broken_model" in comment
    assert "COMPILE ERROR" in comment


def test_format_downstream_count():
    manifest = {
        "metadata": {"project_name": "my_project"},
        "nodes": {},
        "child_map": {
            "model.my_project.fct_revenue": [
                "model.my_project.child_a",
                "model.my_project.child_b",
            ],
            "model.my_project.child_a": ["model.my_project.grandchild"],
            "model.my_project.child_b": [],
            "model.my_project.grandchild": [],
        },
    }
    response = _make_response(
        results=[
            {
                "model_name": "fct_revenue",
                "has_error": False,
                "error_message": None,
                "high": [],
                "medium": [],
                "low": [],
                "info": [],
            }
        ],
        models_with_high_risk=0,
    )
    comment = format_comment(response, manifest)
    # fct_revenue has 3 downstream models (child_a, child_b, grandchild)
    assert "3" in comment


def test_marker_present():
    for results, high in [
        ([], 0),
        (
            [
                {
                    "model_name": "m",
                    "has_error": False,
                    "error_message": None,
                    "high": [],
                    "medium": [],
                    "low": [],
                    "info": [],
                }
            ],
            0,
        ),
    ]:
        comment = format_comment(_make_response(results=results, models_with_high_risk=high), EMPTY_MANIFEST)
        assert MARKER in comment


def test_update_vs_post_logic():
    comments_with_marker = [
        {"id": 42, "body": f"some old text\n{MARKER}\nmore text"},
        {"id": 99, "body": "unrelated comment"},
    ]
    comments_without_marker = [
        {"id": 99, "body": "unrelated comment"},
    ]

    with patch("scripts.post_comment._github_request", return_value=comments_with_marker):
        result = find_existing_comment("fake-token", "owner/repo", 1)
    assert result == 42

    with patch("scripts.post_comment._github_request", return_value=comments_without_marker):
        result = find_existing_comment("fake-token", "owner/repo", 1)
    assert result is None


def test_build_downstream_map():
    manifest = {
        "child_map": {
            "model.proj.a": ["model.proj.b", "model.proj.c"],
            "model.proj.b": ["model.proj.d"],
            "model.proj.c": [],
            "model.proj.d": [],
            "test.proj.some_test": ["model.proj.a"],
        }
    }
    dm = _build_downstream_map(manifest)
    assert dm["a"] == 3  # b, c, d
    assert dm["b"] == 1  # d
    assert dm["c"] == 0
    assert dm["d"] == 0
    assert "some_test" not in dm
