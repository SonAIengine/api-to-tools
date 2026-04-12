# Installation

## Basic Install

```bash
pip install api-to-tools
```

Requires Python 3.10+.

## Optional Extras

```bash
# Browser-based crawling (Playwright)
pip install 'api-to-tools[crawler]'
python -m playwright install chromium

# WebSocket/SSE executor
pip install 'api-to-tools[websocket]'
```

## From Source

```bash
git clone https://github.com/SonAIengine/api-to-tools.git
cd api-to-tools
pip install -e '.[dev]'
```
