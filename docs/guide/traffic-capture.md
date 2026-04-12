# Traffic Capture

Capture browser traffic and convert it to Tool definitions — no Swagger required.

## HAR Files

Export HAR from browser DevTools (Network tab → Export HAR):

```python
from api_to_tools import discover

tools = discover("recording.har")
```

## Live Proxy Capture

Use the built-in HTTP proxy to record traffic in real-time:

```python
from api_to_tools.proxy import TrafficRecorder

with TrafficRecorder(port=8080, target_host="api.example.com") as recorder:
    print("Set browser proxy to http://localhost:8080")
    input("Press Enter when done browsing...")

tools = recorder.to_tools()
recorder.save_har("captured.har")
```

### Quick Capture

Record for a fixed duration:

```python
from api_to_tools.proxy import capture_traffic

tools = capture_traffic(port=8080, duration=60, target_host="api.example.com")
```

## What Gets Captured

- JSON API calls (request + response)
- Query parameters with inferred types
- Request body schema (JSON, form-encoded)
- Response schema (inferred from JSON)
- Path parameter normalization (numeric IDs → `{id}`, UUIDs → `{uuid}`)
- Duplicate endpoint grouping and merging

## What Gets Filtered

- Static assets (JS, CSS, images, fonts)
- CORS preflight (OPTIONS)
- Analytics/tracking requests
- Redirects (301, 302)
- Next.js/Nuxt internal routes
