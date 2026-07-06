import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.post_comment import (
    MARKER,
    _build_criticality_map,
    _build_downstream_map,
    _build_downstream_names_map,
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


def test_feedback_footer_rendered():
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
    comment = format_comment(
        response, EMPTY_MANIFEST, api_base_url="https://api.badaadata.com"
    )
    assert "Was this risk assessment accurate?" in comment
    assert "https://api.badaadata.com/feedback/test-uuid?vote=up" in comment
    assert "https://api.badaadata.com/feedback/test-uuid?vote=down" in comment
    assert "https://api.badaadata.com/feedback/test-uuid" in comment


def test_feedback_footer_strips_v1_suffix():
    response = _make_response(results=[], models_with_high_risk=0)
    # Simulate caller accidentally passing the full /v1 path as base URL
    comment = format_comment(
        response, EMPTY_MANIFEST, api_base_url="https://api.badaadata.com/v1"
    )
    assert "https://api.badaadata.com/feedback/test-uuid" in comment
    assert "/v1/feedback/" not in comment


def test_feedback_footer_absent_without_request_id():
    response = {
        "dialect": "snowflake",
        "total_models": 0,
        "models_with_high_risk": 0,
        "results": [],
    }
    comment = format_comment(
        response, EMPTY_MANIFEST, api_base_url="https://api.badaadata.com"
    )
    assert "Was this risk assessment accurate?" not in comment


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


def test_build_downstream_names_map():
    manifest = {
        "child_map": {
            "model.proj.fct_revenue": ["model.proj.rpt_b", "model.proj.rpt_a"],
            "model.proj.rpt_a": ["model.proj.dash_x"],
            "model.proj.rpt_b": [],
            "model.proj.dash_x": [],
            "test.proj.some_test": ["model.proj.fct_revenue"],
        }
    }
    names = _build_downstream_names_map(manifest)
    assert names["fct_revenue"] == ["dash_x", "rpt_a", "rpt_b"]
    assert names["rpt_a"] == ["dash_x"]
    assert names["rpt_b"] == []
    assert "some_test" not in names


def _critical_manifest(placement: str, model_name: str = "fct_revenue") -> dict:
    """Build a manifest with a single model flagged critical via the given placement."""
    node = {"name": model_name, "config": {}, "meta": {}, "tags": []}
    if placement == "config_meta":
        node["config"] = {"meta": {"semantic_risk_critical": True}}
    elif placement == "node_meta":
        node["meta"] = {"semantic_risk_critical": True}
    elif placement == "config_tags":
        node["config"] = {"tags": ["semantic_risk_critical"]}
    elif placement == "node_tags":
        node["tags"] = ["semantic_risk_critical"]
    return {
        "metadata": {"project_name": "my_project"},
        "nodes": {f"model.my_project.{model_name}": node},
        "child_map": {},
    }


@pytest.mark.parametrize(
    "placement", ["config_meta", "node_meta", "config_tags", "node_tags"]
)
def test_build_criticality_map_detects_each_placement(placement):
    manifest = _critical_manifest(placement)
    critical = _build_criticality_map(manifest)
    assert critical.get("fct_revenue") is True


def test_build_criticality_map_not_flagged():
    manifest = {
        "metadata": {"project_name": "my_project"},
        "nodes": {
            "model.my_project.fct_revenue": {
                "name": "fct_revenue",
                "config": {},
                "meta": {},
                "tags": [],
            }
        },
        "child_map": {},
    }
    critical = _build_criticality_map(manifest)
    assert "fct_revenue" not in critical


def _high_result(model_name: str) -> dict:
    return {
        "model_name": model_name,
        "has_error": False,
        "error_message": None,
        "high": [
            {
                "entity": "FILTER",
                "change_type": "REMOVED",
                "identifier": "WHERE:status",
                "severity": "HIGH",
                "reason": "A WHERE filter was removed.",
                "old_value": "status = 'active'",
                "new_value": None,
            }
        ],
        "medium": [],
        "low": [],
        "info": [],
    }


def _clean_result(model_name: str) -> dict:
    return {
        "model_name": model_name,
        "has_error": False,
        "error_message": None,
        "high": [],
        "medium": [],
        "low": [],
        "info": [],
    }


def test_critical_model_badge_and_footer_alert():
    manifest = _critical_manifest("config_meta", model_name="fct_revenue")
    response = _make_response(results=[_high_result("fct_revenue")], models_with_high_risk=1)
    comment = format_comment(response, manifest)

    assert "MODEL MARKED AS CRITICAL" in comment
    assert "Critical model(s) affected" in comment
    assert "fct_revenue" in comment


def test_uncritical_model_has_no_criticality_signals():
    manifest = {
        "metadata": {"project_name": "my_project"},
        "nodes": {
            "model.my_project.fct_revenue": {
                "name": "fct_revenue",
                "config": {},
                "meta": {},
                "tags": [],
            }
        },
        "child_map": {},
    }
    response = _make_response(results=[_high_result("fct_revenue")], models_with_high_risk=1)
    comment = format_comment(response, manifest)

    assert "MODEL MARKED AS CRITICAL" not in comment
    assert "Critical model(s) affected" not in comment


def test_critical_model_with_risk_sorted_above_noncritical():
    manifest = {
        "metadata": {"project_name": "my_project"},
        "nodes": {
            "model.my_project.zzz_normal": {
                "name": "zzz_normal",
                "config": {},
                "meta": {},
                "tags": [],
            },
            "model.my_project.fct_revenue": {
                "name": "fct_revenue",
                "config": {"meta": {"semantic_risk_critical": True}},
                "meta": {},
                "tags": [],
            },
        },
        "child_map": {},
    }
    # Non-critical model listed first in the API response; critical model should
    # still be sorted to the top of the rendered comment.
    response = _make_response(
        results=[_high_result("zzz_normal"), _high_result("fct_revenue")],
        models_with_high_risk=2,
    )
    comment = format_comment(response, manifest)

    assert comment.index("fct_revenue") < comment.index("zzz_normal")


def test_downstream_names_appear_in_rendered_comment():
    manifest = {
        "metadata": {"project_name": "my_project"},
        "nodes": {},
        "child_map": {
            "model.my_project.fct_revenue": [
                "model.my_project.rpt_a",
                "model.my_project.rpt_b",
            ],
            "model.my_project.rpt_a": [],
            "model.my_project.rpt_b": [],
        },
    }
    response = _make_response(results=[_high_result("fct_revenue")], models_with_high_risk=1)
    comment = format_comment(response, manifest)

    assert "downstream model(s) may be affected" in comment
    assert "rpt_a" in comment
    assert "rpt_b" in comment


def test_critical_model_without_risk_change_no_footer_alert():
    manifest = _critical_manifest("config_meta", model_name="fct_revenue")
    response = _make_response(results=[_clean_result("fct_revenue")], models_with_high_risk=0)
    comment = format_comment(response, manifest)

    assert "Critical model(s) affected" not in comment
