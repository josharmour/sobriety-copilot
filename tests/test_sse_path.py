"""SSE streaming-path audit: verify headers and unbuffered delivery.

Usage:
    # Start the app first (or point at a running instance):
    pytest tests/test_sse_path.py -v

    # Or run directly with a custom base URL:
    python tests/test_sse_path.py --base-url http://localhost:5000
"""

import json
import os
import re
import urllib.error
import urllib.request

BASE_URL = os.environ.get("SSE_TEST_BASE_URL", "http://localhost:5000")
TIMEOUT = 60  # generous timeout for slow generations


def _sse_events(response: urllib.request.http.client.HTTPResponse):
    """Parse an SSE response body into a list of event dicts.

    Each event dict has:
        - ``type``: ``"comment"``, ``"data"``, or ``"unknown"``
        - ``raw``: the raw line
        - For data events, ``data``: the parsed JSON payload
    """
    buf = b""
    events = []
    for chunk in iter(lambda: response.read(4096), b""):
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            text = raw.decode("utf-8")
            lines = text.split("\n")
            data_lines = []
            for line in lines:
                if line.startswith(":"):
                    events.append({"type": "comment", "raw": line})
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
                elif line.strip():
                    events.append({"type": "unknown", "raw": line})
            if data_lines:
                payload = json.loads("".join(data_lines))
                events.append({"type": "data", "data": payload, "raw": raw.decode()})
    return events


def test_sse_media_type():
    """The /api/chat endpoint must advertise text/event-stream."""
    body = json.dumps({"message": "ping"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        # A 422 (validation) or other error means we hit the server but the
        # request was malformed.  Still check the response headers for the
        # Content-Type on the error — nginx could mis-label it there too.
        resp = exc.fp  # type: ignore[assignment]

    ct = resp.headers.get("Content-Type", "")
    assert "text/event-stream" in ct, (
        f"Expected Content-Type containing 'text/event-stream', got {ct!r}"
    )


def test_sse_buffering_headers():
    """Must include headers that disable buffering at every layer."""
    body = json.dumps({"message": "ping"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)

    cc = resp.headers.get("Cache-Control", "")
    assert "no-cache" in cc, f"Missing Cache-Control: no-cache (got {cc!r})"

    # nginx consumes X-Accel-* response headers rather than passing them to
    # the client, so this is only observable when hitting uvicorn directly.
    # When present it must be 'no'; through the proxy its absence is expected.
    xab = resp.headers.get("X-Accel-Buffering")
    assert xab is None or xab == "no", (
        f"X-Accel-Buffering should be 'no' when present, got {xab!r}"
    )


def test_first_event_is_priming_comment():
    """The very first SSE event must be an SSE comment (': primed') so the
    TCP connection and proxy buffers are committed before any data."""
    body = json.dumps({"message": "hello"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)

    # Read just the first chunk — enough to get the first event
    raw = resp.read(256)
    assert raw.startswith(b":"), (
        f"First SSE line should be a comment (': primed\\n\\n'), got {raw[:60]!r}"
    )
    # Normalise newlines and check for our priming marker
    first_line = raw.split(b"\n")[0].decode("utf-8").strip()
    assert ": primed" in first_line, (
        f"Expected ': primed' comment as first SSE event, got {first_line!r}"
    )


def test_sources_arrive_first():
    """'sources' must be the first substantive payload. Diagnostic events
    (server_timing_ms) are emitted before it and are allowed."""
    body = json.dumps({"message": "hello"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)

    events = _sse_events(resp)

    # Skip the priming comment
    data_events = [e for e in events if e["type"] == "data"]

    assert len(data_events) > 0, "No data events found in SSE stream"
    diagnostic_keys = {"server_timing_ms"}
    substantive = [
        e for e in data_events if not (set(e["data"].keys()) & diagnostic_keys)
    ]
    assert len(substantive) > 0, "Only diagnostic events found in SSE stream"
    assert "sources" in substantive[0]["data"], (
        f"First substantive data event should contain 'sources', got keys: "
        f"{list(substantive[0]['data'].keys())}"
    )


def test_stream_closes_with_done():
    """The stream should end with a {done: true} event."""
    body = json.dumps({"message": "what is step 1?"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)

    events = _sse_events(resp)
    data_events = [e for e in events if e["type"] == "data"]

    assert len(data_events) >= 2, "Need at least sources + done events"
    last = data_events[-1]["data"]
    assert last.get("done") is True, (
        f"Last data event should be {{done: true}}, got {last}"
    )


# ---- CLI runner (for use without pytest) ----
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SSE path audit")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    failures = []
    for name, fn in [
        ("media_type", test_sse_media_type),
        ("buffering_headers", test_sse_buffering_headers),
        ("first_comment", test_first_event_is_priming_comment),
        ("sources_first", test_sources_arrive_first),
        ("ends_with_done", test_stream_closes_with_done),
    ]:
        print(f"  [{name}] ", end="", flush=True)
        try:
            fn()
            print("PASS")
        except Exception as exc:
            print(f"FAIL — {exc}")
            failures.append(name)

    if failures:
        print(f"\nFAILED: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("\nAll SSE path checks passed.")
