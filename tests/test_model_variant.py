"""Tests for A/B model variant routing (LLM_MODEL_FT / model_variant).

Tests the contract:
- No model_variant field → default model (LLM_MODEL)
- model_variant="ft" + LLM_MODEL_FT set → FT model, SSE stream
- model_variant="ft" + LLM_MODEL_FT unset → 400 "not configured"
- model_variant="bogus" → 400 "unsupported"

Usage:
    # Start the app first, then:
    pytest tests/test_model_variant.py -v

    # Or run directly:
    python tests/test_model_variant.py --base-url http://localhost:5000
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = "http://localhost:5000"
TIMEOUT = 30


def _post_chat(payload: dict) -> tuple[int, dict | list | str]:
    """POST to /api/chat and return (status_code, parsed_body)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        events = _sse_events(resp)
        return (resp.status, events)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(err_body)
        except json.JSONDecodeError:
            detail = err_body
        return (exc.code, detail)


def test_health_ok():
    """Sanity check — the server must be up."""
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=10)
        data = json.loads(resp.read().decode())
        assert data.get("status") == "ok", f"Expected status=ok, got {data}"
    except Exception as exc:
        print(f"SKIP: server unreachable ({exc})")
        raise


def test_default_variant():
    """model_variant absent -> uses default model (should succeed with SSE)."""
    code, body = _post_chat({"message": "ping"})
    assert code == 200, f"Expected 200, got {code}: {body}"
    events = body if isinstance(body, list) else []
    assert any("sources" in e for e in events), "Expected 'sources' in SSE events"


def test_default_variant_explicit():
    """model_variant='default' -> uses default model."""
    code, body = _post_chat({"message": "ping", "model_variant": "default"})
    assert code == 200, f"Expected 200, got {code}: {body}"
    events = body if isinstance(body, list) else []
    assert any("sources" in e for e in events), "Expected 'sources' in SSE events"


def test_invalid_variant():
    """model_variant='bogus' -> 400."""
    code, body = _post_chat({"message": "ping", "model_variant": "bogus"})
    assert code == 400, f"Expected 400, got {code}: {body}"
    detail = body if isinstance(body, dict) else {"detail": str(body)}
    err = json.dumps(detail).lower()
    assert "bogus" in err, f"Expected rejection mentioning 'bogus', got: {detail}"


def test_ft_without_config():
    """model_variant='ft' when no LLM_MODEL_FT env -> 400."""
    if os.environ.get("LLM_MODEL_FT", "").strip():
        print("SKIP: LLM_MODEL_FT is set")
        return
    code, body = _post_chat({"message": "ping", "model_variant": "ft"})
    assert code == 400, f"Expected 400, got {code}: {body}"
    detail = body if isinstance(body, dict) else {"detail": str(body)}
    err = json.dumps(detail).lower()
    assert "not configured" in err or "llm_model_ft" in err, (
        f"Expected 'not configured' or 'LLM_MODEL_FT' in error, got: {detail}"
    )


def test_ft_with_config():
    """model_variant='ft' when LLM_MODEL_FT IS set -> 200 with SSE."""
    if not os.environ.get("LLM_MODEL_FT", "").strip():
        print("SKIP: LLM_MODEL_FT is not set")
        return
    code, body = _post_chat({"message": "ping", "model_variant": "ft"})
    assert code == 200, f"Expected 200, got {code}: {body}"
    events = body if isinstance(body, list) else []
    assert any("sources" in e for e in events), "Expected 'sources' in SSE events"


def _sse_events(response) -> list[dict]:
    """Parse SSE body into a list of event dicts."""
    buf = b""
    for chunk in iter(lambda: response.read(4096), b""):
        buf += chunk
    events = []
    text = buf.decode("utf-8")
    for raw_event in text.split("\n\n"):
        lines = raw_event.strip().split("\n")
        data_lines = [line[6:] for line in lines if line.startswith("data: ")]
        if data_lines:
            payload = json.loads("".join(data_lines))
            events.append(payload)
    return events


# ---- CLI runner ----
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Model variant routing tests")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    failures = []
    test_fns = [
        ("health_ok", test_health_ok),
        ("default_variant", test_default_variant),
        ("default_variant_explicit", test_default_variant_explicit),
        ("invalid_variant", test_invalid_variant),
        ("ft_without_config", test_ft_without_config),
        ("ft_with_config", test_ft_with_config),
    ]
    for name, fn in test_fns:
        print(f"  [{name}] ", end="", flush=True)
        try:
            fn()
            print("PASS")
        except Exception as exc:
            print(f"FAIL - {exc}")
            failures.append(name)

    if failures:
        print(f"\nFAILED: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("\nAll model variant tests passed.")
