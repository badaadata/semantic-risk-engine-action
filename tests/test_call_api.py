import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.call_api import call_api, main


def _write_payload(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"models": [], "dialect": "snowflake"}))
    return payload_file


def test_call_api_success(tmp_path):
    payload_file = _write_payload(tmp_path)
    fake_resp = BytesIO(b'{"results": []}')

    with patch("scripts.call_api.urllib.request.urlopen", return_value=fake_resp):
        result = call_api(str(payload_file), "https://api.example.com/v1/analyze", "sre_test")

    assert result == {"ok": True, "body": '{"results": []}'}


def test_call_api_rejects_non_https_endpoint(tmp_path):
    payload_file = _write_payload(tmp_path)

    with patch("scripts.call_api.urllib.request.urlopen") as mock_urlopen:
        result = call_api(str(payload_file), "http://api.example.com/v1/analyze", "sre_test")

    mock_urlopen.assert_not_called()  # must not even attempt the request
    assert result["ok"] is False
    assert result["annotation"] == "error"
    assert "non-HTTPS" in result["message"]


def test_call_api_auth_error_is_misconfiguration(tmp_path):
    payload_file = _write_payload(tmp_path)
    err = urllib.error.HTTPError(
        url="https://api.example.com/v1/analyze", code=401, msg="Unauthorized",
        hdrs=None, fp=BytesIO(b"invalid API key"),
    )

    with patch("scripts.call_api.urllib.request.urlopen", side_effect=err):
        result = call_api(str(payload_file), "https://api.example.com/v1/analyze", "sre_bad")

    assert result["ok"] is False
    assert result["annotation"] == "error"
    assert "401" in result["message"]


def test_call_api_server_error_is_warning(tmp_path):
    payload_file = _write_payload(tmp_path)
    err = urllib.error.HTTPError(
        url="https://api.example.com/v1/analyze", code=503, msg="Service Unavailable",
        hdrs=None, fp=BytesIO(b"try again later"),
    )

    with patch("scripts.call_api.urllib.request.urlopen", side_effect=err):
        result = call_api(str(payload_file), "https://api.example.com/v1/analyze", "sre_test")

    assert result["ok"] is False
    assert result["annotation"] == "warning"
    assert "503" in result["message"]


def test_call_api_network_error_is_warning(tmp_path):
    payload_file = _write_payload(tmp_path)
    err = urllib.error.URLError("timed out")

    with patch("scripts.call_api.urllib.request.urlopen", side_effect=err):
        result = call_api(str(payload_file), "https://api.example.com/v1/analyze", "sre_test")

    assert result["ok"] is False
    assert result["annotation"] == "warning"
    assert "timed out" in result["message"]


def test_main_never_exits_nonzero_on_failure(tmp_path, capsys, monkeypatch):
    payload_file = _write_payload(tmp_path)
    err = urllib.error.URLError("connection refused")

    monkeypatch.setattr(
        sys, "argv",
        ["call_api.py", "--payload", str(payload_file), "--api-url", "https://api.example.com/v1/analyze"],
    )
    monkeypatch.setenv("SRE_API_KEY", "sre_test")

    with patch("scripts.call_api.urllib.request.urlopen", side_effect=err):
        main()  # must not raise SystemExit

    captured = capsys.readouterr()
    assert "::warning::" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["analysis_failed"] is True


def test_main_reports_error_when_api_key_missing(tmp_path, capsys, monkeypatch):
    """Fork PRs never receive the secret — this must warn, not crash or block."""
    payload_file = _write_payload(tmp_path)

    monkeypatch.setattr(
        sys, "argv",
        ["call_api.py", "--payload", str(payload_file), "--api-url", "https://api.example.com/v1/analyze"],
    )
    monkeypatch.delenv("SRE_API_KEY", raising=False)

    main()  # must not raise SystemExit, must not even attempt the request

    captured = capsys.readouterr()
    assert "::error::" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["analysis_failed"] is True
