"""Cross-platform transcription history viewer.

Serves a single-page web UI on localhost and opens it in the default browser.
Works on macOS, Windows, and Linux with zero extra dependencies (uses only
Python's built-in http.server and webbrowser modules).

Usage from the main app:
    HistoryWindow.show()               # spawns the server + opens browser
    HistoryWindow.refresh_if_visible()  # no-op (browser polls via JS)

Direct launch:
    python3 -m app.gui.history_window
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LOG = logging.getLogger("dictator")

HISTORY_FILE = Path.home() / ".config" / "dictator" / "history.json"


def _load_history() -> list[dict]:
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_history(entries: list[dict]) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
        tmp.replace(HISTORY_FILE)
    except Exception:
        pass


class _Handler(BaseHTTPRequestHandler):
    """Handles GET / (HTML page), GET /api/history, and POST /api/* actions."""

    def log_message(self, format, *args):
        pass  # silence console spam

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            q = parse_qs(parsed.query).get("q", [""])[0]
            entries = _load_history()
            if q:
                q_lower = q.lower()
                entries = [e for e in entries if q_lower in e.get("text", "").lower()]
            self._json_response({"entries": entries, "total": len(_load_history())})
        elif parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._html_response(_HTML_PAGE)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        parsed = urlparse(self.path)

        if parsed.path == "/api/delete":
            entry_id = body.get("id", "")
            entries = _load_history()
            entries = [e for e in entries if e.get("id") != entry_id]
            _save_history(entries)
            self._json_response({"ok": True})

        elif parsed.path == "/api/clear":
            _save_history([])
            self._json_response({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Public API (called from main app) ──────────────────────────────────

class HistoryWindow:
    """Launches the history viewer as a subprocess."""

    _proc: subprocess.Popen | None = None

    @classmethod
    def show(cls):
        if cls._proc is not None and cls._proc.poll() is None:
            return  # already running
        cls._proc = subprocess.Popen(
            [sys.executable, "-m", "app.gui.history_window"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )

    @classmethod
    def refresh_if_visible(cls):
        pass  # browser polls automatically


# ── Standalone entry point ─────────────────────────────────────────────

def _serve():
    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Dictator history → {url}")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ── HTML / CSS / JS (single-page app) ──────────────────────────────────

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dictator — Transcription History</title>
<style>
  :root {
    --bg: #1a1a2e;
    --bg-card: #22223a;
    --bg-hover: #2a2a4a;
    --bg-select: #3a3a5c;
    --fg: #e0e0e0;
    --fg-dim: #888;
    --fg-time: #8aacff;
    --accent: #4a9eff;
    --border: #333;
    --radius: 10px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--fg);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Header */
  .header {
    padding: 20px 24px 12px;
    flex-shrink: 0;
  }
  .header h1 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 12px;
    color: #fff;
  }
  .search-box {
    width: 100%;
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--fg);
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
  }
  .search-box:focus {
    border-color: var(--accent);
  }
  .search-box::placeholder {
    color: var(--fg-dim);
  }

  /* Entry list */
  .entries {
    flex: 1;
    overflow-y: auto;
    padding: 4px 24px;
  }
  .entries::-webkit-scrollbar { width: 6px; }
  .entries::-webkit-scrollbar-track { background: transparent; }
  .entries::-webkit-scrollbar-thumb { background: #444; border-radius: 3px; }

  .entry {
    display: flex;
    align-items: flex-start;
    padding: 12px 14px;
    margin-bottom: 2px;
    border-radius: var(--radius);
    cursor: pointer;
    transition: background 0.15s;
    gap: 14px;
    position: relative;
  }
  .entry:hover {
    background: var(--bg-hover);
  }
  .entry.selected {
    background: var(--bg-select);
  }
  .entry-time {
    font-size: 12px;
    color: var(--fg-time);
    min-width: 90px;
    padding-top: 2px;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }
  .entry-text {
    font-size: 14px;
    line-height: 1.5;
    word-break: break-word;
    flex: 1;
  }
  .entry-actions {
    display: none;
    gap: 4px;
    flex-shrink: 0;
    padding-top: 1px;
  }
  .entry:hover .entry-actions {
    display: flex;
  }
  .entry-btn {
    background: none;
    border: 1px solid var(--border);
    color: var(--fg-dim);
    padding: 3px 10px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 11px;
    transition: all 0.15s;
  }
  .entry-btn:hover {
    color: #fff;
    border-color: var(--accent);
    background: var(--accent);
  }
  .entry-btn.del:hover {
    border-color: #e05555;
    background: #e05555;
  }

  .empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--fg-dim);
  }
  .empty-state .icon { font-size: 40px; margin-bottom: 12px; }
  .empty-state p { font-size: 14px; }

  /* Footer toolbar */
  .toolbar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 24px;
    border-top: 1px solid var(--border);
    background: var(--bg-card);
  }
  .toolbar-left { display: flex; gap: 8px; }
  .toolbar-btn {
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--fg);
    padding: 6px 16px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.15s;
  }
  .toolbar-btn:hover {
    border-color: var(--accent);
    color: #fff;
  }
  .toolbar-btn.danger:hover {
    border-color: #e05555;
    color: #e05555;
  }
  .count {
    font-size: 12px;
    color: var(--fg-dim);
  }

  /* Copied toast */
  .toast {
    position: fixed;
    bottom: 60px;
    left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: var(--accent);
    color: #fff;
    padding: 8px 20px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    opacity: 0;
    transition: all 0.3s;
    pointer-events: none;
    z-index: 100;
  }
  .toast.show {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
</style>
</head>
<body>

<div class="header">
  <h1>Transcription History</h1>
  <input class="search-box" type="text" placeholder="Search transcriptions..." id="search">
</div>

<div class="entries" id="entries"></div>

<div class="toolbar">
  <div class="toolbar-left">
    <button class="toolbar-btn" onclick="copySelected()">Copy</button>
    <button class="toolbar-btn danger" onclick="clearAll()">Clear All</button>
  </div>
  <span class="count" id="count"></span>
</div>

<div class="toast" id="toast">Copied to clipboard</div>

<script>
let entries = [];
let total = 0;
let selectedId = null;

const searchEl = document.getElementById('search');
const entriesEl = document.getElementById('entries');
const countEl = document.getElementById('count');
const toastEl = document.getElementById('toast');

async function load() {
  const q = searchEl.value.trim();
  const url = '/api/history' + (q ? '?q=' + encodeURIComponent(q) : '');
  try {
    const r = await fetch(url);
    const data = await r.json();
    entries = data.entries || [];
    total = data.total || 0;
  } catch(e) {
    entries = [];
    total = 0;
  }
  render();
}

function render() {
  const q = searchEl.value.trim();
  if (entries.length === 0) {
    entriesEl.innerHTML = `
      <div class="empty-state">
        <div class="icon">🎤</div>
        <p>${q ? 'No matching transcriptions' : 'No transcriptions yet'}</p>
        <p style="margin-top:6px">${q ? 'Try a different search' : 'Hold your PTT key and start speaking'}</p>
      </div>`;
    countEl.textContent = q ? `0 of ${total} transcriptions` : '0 transcriptions';
    return;
  }

  entriesEl.innerHTML = entries.map(e => `
    <div class="entry ${e.id === selectedId ? 'selected' : ''}"
         data-id="${e.id}" onclick="select('${e.id}')">
      <div class="entry-time">${formatTime(e.timestamp)}</div>
      <div class="entry-text">${esc(e.text)}</div>
      <div class="entry-actions">
        <button class="entry-btn" onclick="event.stopPropagation(); copyEntry('${e.id}')">Copy</button>
        <button class="entry-btn del" onclick="event.stopPropagation(); deleteEntry('${e.id}')">Delete</button>
      </div>
    </div>`).join('');

  countEl.textContent = q
    ? `${entries.length} of ${total} transcriptions`
    : `${total} transcriptions`;
}

function select(id) {
  if (selectedId === id) {
    copyEntry(id);
    return;
  }
  selectedId = id;
  render();
}

function copyEntry(id) {
  const e = entries.find(x => x.id === id);
  if (e) {
    navigator.clipboard.writeText(e.text);
    showToast();
  }
}

function copySelected() {
  if (selectedId) copyEntry(selectedId);
}

async function deleteEntry(id) {
  await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id})
  });
  if (selectedId === id) selectedId = null;
  load();
}

async function clearAll() {
  if (!confirm(`Delete all ${total} transcriptions?`)) return;
  await fetch('/api/clear', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  selectedId = null;
  load();
}

function showToast() {
  toastEl.classList.add('show');
  setTimeout(() => toastEl.classList.remove('show'), 1500);
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    }
    return d.toLocaleDateString([], {month: 'short', day: 'numeric'}) +
           ', ' + d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  } catch(e) { return iso; }
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Search
let debounce;
searchEl.addEventListener('input', () => {
  clearTimeout(debounce);
  debounce = setTimeout(load, 200);
});

// Poll for new transcriptions every 2s
setInterval(load, 2000);

// Initial load
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    _serve()
