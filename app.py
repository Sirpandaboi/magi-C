"""magi-C Lexical and Syntax Analyzer -- single-file Flask web app.

Run with:   python app.py        ->  http://localhost:5000
"""

from __future__ import annotations

import os
import re
import sys
import threading
from ast import literal_eval
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_from_directory

# --- the ``ui/`` folder itself; the navbar PNGs live beside this file --- #
_UI_DIR = os.path.dirname(os.path.abspath(__file__))

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# --- make ``Lexer.py`` (one level up) importable, however we are launched --- #
_PROJECT_ROOT = os.path.dirname(_UI_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lexer import Lexer
from core.errors import LexerError
from core.tokens import Token
from parser.Parser import LL1Parser

app = Flask(__name__)

# Bound scanning time so malformed input cannot hang a web request.
SCAN_TIMEOUT_SECONDS = 5.0

# --- Editor starts blank (no preloaded sample program) --- #
SAMPLE_PROGRAM = ""


# --- Helpers --------------------------------------------------------------- #
def serialize(tokens: list[Token]) -> list[dict]:
    """Token -> plain JSON object (exactly type / value / line / column)."""
    return [
        {"type": t.type, "value": t.value, "line": t.line, "column": t.column}
        for t in tokens
    ]


def _run_lexer(lexer: Lexer) -> list[Token]:
    """Return tokens while retaining the lexer's partial stream on failure."""
    return lexer.tokenize()


def _scan_into(lexer: Lexer, result: dict) -> None:
    """Thread body: run the scan and stash either tokens or the exception."""
    try:
        result["tokens"] = _run_lexer(lexer)
    except Exception as exc:                     # noqa: BLE001 (re-raised via JSON)
        result["error"] = exc


def error_line(exc: Exception) -> int:
    """Line of a LexerError, tolerant of builds that omit/rename the field."""
    return int(getattr(exc, "line", 0) or 0)


def error_column(exc: Exception) -> int:
    """Column of a LexerError, accepting either ``.column`` or ``.col``."""
    return int(getattr(exc, "column", getattr(exc, "col", 0)) or 0)


_ERROR_TEXT_RE = re.compile(r"^Lexical Error \[Line \d+, Col \d+: (.*)\]$", re.DOTALL)


def inner_message(exc: LexerError) -> str:
    """Return only the diagnostic text, without LexerError's ``[...]`` wrapper.

    LexerError renders itself as "Lexical Error [Line L, Col C: <message>]",
    but the UI re-formats errors as "line #L:C - <message>", so it needs just
    the bare <message>.  Prefers an explicit ``.message`` when a build stores
    one, then unwraps the rendered form, and finally falls back to raw text.
    """
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    raw = str(exc)
    match = _ERROR_TEXT_RE.match(raw)
    if match:
        return match.group(1)
    return raw


# --- Routes ---------------------------------------------------------------- #
@app.get("/")
def index():
    return render_template_string(PAGE, sample_program=SAMPLE_PROGRAM)


@app.get("/LOGO TOPLEFT.png")
def serve_logo_topleft():
    """Top-left navbar mark -- route mirrors the on-disk name in ``ui/``."""
    return send_from_directory(_ASSETS_DIR, "LOGO TOPLEFT.png")


@app.get("/MIDDLE.png")
def serve_middle_logo():
    """Centered navbar wordmark -- route mirrors the on-disk name in ``ui/``."""
    return send_from_directory(_ASSETS_DIR, "MIDDLE.png")


def _scan_source(source: str) -> tuple[list[Token], list[dict]]:
    """Collect lexical diagnostics and retain tokens produced before a failure."""
    lexer = Lexer(source)

    # Run the scan on a worker thread so a scanner that never returns (a keyword
    # prefix sitting against an invalid delimiter, say) cannot wedge the request.
    result: dict = {}
    worker = threading.Thread(
        target=_scan_into, args=(lexer, result), daemon=True
    )
    worker.start()
    worker.join(SCAN_TIMEOUT_SECONDS)

    errors = [
        {
            "message": inner_message(error),
            "line": error_line(error),
            "column": error_column(error),
            "formatted": str(error),
        }
        for error in list(lexer.errors)
    ]
    exc = result.get("error")
    if worker.is_alive():
        errors.append({
            "message": ("Scanning timed out -- the source may contain input "
                        "the scanner cannot advance past."),
            "line": error_line(lexer),
            "column": error_column(lexer),
            "formatted": "Lexical Error: scan timed out.",
        })
    elif exc is not None and exc not in lexer.errors:
        errors.append({
            "message": (inner_message(exc) if isinstance(exc, LexerError)
                        else f"{type(exc).__name__}: {exc}"),
            "line": error_line(exc),
            "column": error_column(exc),
            "formatted": str(exc),
        })
    return list(result.get("tokens", lexer.tokens)), errors


_EXPECTED_TOKENS_RE = re.compile(
    r"(?:\. Expected: | \(expected one of: )(\[.*\])\)?$", re.DOTALL
)


def _parse_source(tokens: list[Token], source: str) -> dict:
    """Pass positioned lexer tokens to the parser, including a positioned EOF."""
    parser_tokens = list(tokens)
    if not parser_tokens or parser_tokens[-1].type not in {"EOF", "$"}:
        parser_tokens.append(Token(
            "EOF", "", source.count("\n") + 1,
            len(source.rsplit("\n", 1)[-1]) + 1,
        ))

    try:
        result = LL1Parser().parse(parser_tokens)
    except Exception as exc:
        error = {
            "message": f"Parser failure -- {type(exc).__name__}: {exc}",
            "line": 0,
            "column": 0,
            "expected": [],
        }
        return {"ok": False, "skipped": False, "error": error, "errors": [error]}

    errors = []
    if not result.valid:
        message = result.error or "Syntax analysis failed."
        expected = []
        match = _EXPECTED_TOKENS_RE.search(message)
        if match:
            try:
                expected = literal_eval(match.group(1))
                message = message[:match.start()]
            except (SyntaxError, ValueError):
                pass
        # A terminal mismatch names the required token directly. The parser's
        # broader prediction list can describe the following production instead.
        terminal_match = re.match(r"^Expected '(.*?)', got ", message)
        if terminal_match:
            expected = [terminal_match.group(1)]
        errors.append({
            "message": message,
            "line": result.line or 0,
            "column": result.column or 0,
            "expected": expected,
            "formatted": result.error,
        })
    return {
        "ok": result.valid,
        "skipped": False,
        "error": errors[0] if errors else None,
        "errors": errors,
    }


def _analysis_response(include_syntax: bool):
    payload = request.get_json(silent=True)
    source = payload.get("code", "") if isinstance(payload, dict) else None
    if not isinstance(source, str):
        error = {
            "message": "'code' must be a string in a JSON object.",
            "line": 0,
            "column": 0,
            "formatted": "Invalid request payload.",
        }
        return jsonify({
            "ok": False, "tokens": [], "error": error, "errors": [error],
        }), 400

    tokens, errors = _scan_source(source)
    lexical = {
        "ok": not errors,
        "error": errors[0] if errors else None,
        "errors": errors,
    }
    if not include_syntax:
        return jsonify({**lexical, "tokens": serialize(tokens)})

    syntax = {"ok": False, "skipped": True, "error": None, "errors": []}
    if lexical["ok"]:
        syntax = _parse_source(tokens, source)
    return jsonify({
        "ok": lexical["ok"] and syntax["ok"],
        "tokens": serialize(tokens),
        "lexical": lexical,
        "syntax": syntax,
    })


@app.post("/tokenize")
def tokenize_endpoint():
    """Preserve the lexical-only API, including partial tokens and first error."""
    return _analysis_response(include_syntax=False)


@app.post("/analyze")
def analyze_endpoint():
    """Scan source and run syntax analysis when lexical analysis succeeds."""
    return _analysis_response(include_syntax=True)


# --- Inline page (light neo-brutalism + midnight dark mode + cross-features) --- #
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>magi-C &middot; Lexical Analyzer</title>
<style>
  :root {
    --parchment: #F6F3FB;
    --panel: #FFFFFF;
    --header: #F0EAFB;
    --ink: #3E236E;
    --ink-strong: #1E1035;
    --royal: #51308B;
    --nav: #5A398A;
    --gold: #F5D166;
    --emerald: #10B981;
    --emerald-text: #059669;
    --crimson: #DC2626;
    --violet: #8B5CF6;
    --teal: #3E236E;
    --muted: #51308B;
    --faint: #8E7BC0;
    --rule: #E4DCF5;
    --shadow: 4px 4px 0 var(--ink);
    --shadow-strong: 4px 4px 0 var(--ink-strong);
    --mono: "JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, "Courier New", monospace;
  }

  /* MIDNIGHT DARK MODE THEME */
  body.dark-mode {
    --parchment: #0d0b14;
    --panel: #1b1629;
    --header: #22153b;
    --ink: #9d4edd;
    --ink-strong: #f3e8ff;
    --royal: #58217b;
    --nav: #1b1629;
    --gold: #ffd166;
    --emerald: #10B981;
    --emerald-text: #34d399;
    --crimson: #ff6b6b;
    --violet: #7c3aed;
    --teal: #e0aaff;
    --muted: #c7b8ea;
    --faint: #8e7bc0;
    --rule: #331f5c;
    --shadow: 4px 4px 0 #9d4edd;
    --shadow-strong: 4px 4px 0 #f3e8ff;
  }

  * { box-sizing: border-box; }

  html, body { height: 100%; margin: 0; }

  body {
    background: var(--parchment);
    color: var(--ink-strong);
    font-family: var(--mono);
    -webkit-font-smoothing: antialiased;
    zoom: 1.08;
    transform-origin: top left;
    transition: background-color 0.2s ease, color 0.2s ease;
  }

  .app {
    height: calc(100vh / 1.08);
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 16px;
    padding-right: 20px; /* leaves breathing room for right box shadow */
  }

  /* ---------------- navigation ---------------- */
  .nav {
    position: relative;
    flex: none;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 16px;
    background: var(--nav);
    border: 3px solid var(--ink);
    box-shadow: var(--shadow);
  }

  .brand { display: flex; align-items: center; gap: 10px; }

  .brand-slot {
    flex: none;
    width: 76px;
    height: 62px;
    overflow: hidden;
  }
  .brand-slot img {
    display: block;
    height: 136.1px;
    width: auto;
    margin: -37.05px 0 0 -30.6px;
  }

  .nav-mid-slot {
    position: absolute;
    left: 50%;
    top: 50%;
    margin: -20px 0 0 -68px;
    width: 136px;
    height: 40px;
    overflow: hidden;
    pointer-events: none;
  }
  .nav-mid-slot img {
    display: block;
    height: 66.9px;
    width: auto;
    margin: -14.6px 0 0 -47.1px;
  }

  .tabs { display: flex; gap: 12px; margin-left: auto; align-items: center; }

  .tab {
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 1px;
    color: #FFFFFF;
    border: 3px solid var(--ink-strong);
    user-select: none;
    background: var(--violet);
    cursor: pointer;
  }
  .tab.active { background: var(--violet); color: var(--ink-strong); box-shadow: var(--shadow-strong); }
  .tab:hover { filter: brightness(1.1); }

  /* ---------------- workspace ---------------- */
  .workspace {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 42% calc(58% - 16px); /* account for gap so right box doesn't overflow */
    gap: 16px;
  }

  .pane {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--panel);
    border: 3px solid var(--ink);
    box-shadow: var(--shadow);
  }

  .pane-header {
    flex: none;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    background: var(--panel);
    border-bottom: 3px solid var(--royal);
  }
  .pane-header h2 {
    margin: 0;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 1px;
    color: var(--teal);
  }

  .actions { display: flex; gap: 10px; margin-left: auto; flex-wrap: nowrap; }

  /* ---------------- buttons ---------------- */
  .btn {
    font-family: inherit;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 9px 16px;
    color: var(--ink);
    background: var(--panel);
    border: 3px solid var(--ink);
    box-shadow: var(--shadow);
    cursor: pointer;
    transition: transform .05s ease, box-shadow .05s ease;
    white-space: nowrap;
  }
  .btn:hover:not(:disabled) { filter: brightness(.95); }
  .btn:active:not(:disabled) { transform: translate(2px, 2px); box-shadow: 2px 2px 0 var(--ink); }
  .btn:disabled { cursor: wait; opacity: .6; }
  .btn.primary { background: var(--gold); color: #000000; }
  .btn.violet { background: #6D28D9; color: #fff; }

  /* ---------------- standard editor & gutter ---------------- */
  .editor { flex: 1; min-height: 0; display: flex; background: var(--panel); }

  .gutter {
    flex: none;
    width: 56px;
    padding: 14px 12px 14px 0;
    text-align: right;
    background: var(--header);
    border-right: 3px solid var(--ink);
    font-size: 14px;
    line-height: 22px;
    color: var(--faint);
    overflow: hidden;
    user-select: none;
  }
  .ln { display: block; height: 22px; line-height: 22px; }
  .ln.err { background: var(--crimson); color: #fff; font-weight: 800; }

  #code {
    flex: 1;
    min-width: 0;
    padding: 14px;
    border: 0;
    outline: 0;
    resize: none;
    background: var(--panel);
    color: var(--ink-strong);
    font-family: inherit;
    font-size: 14px;
    line-height: 22px;
    tab-size: 4;
    white-space: pre;
    overflow: auto;
  }
  #code::selection { background: var(--gold); color: #000000; }

  /* ---------------- token table ---------------- */
  .table-wrap { flex: 1; min-height: 0; overflow: auto; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }

  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    padding: 9px 12px;
    text-align: left;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    color: #FFFFFF;
    background: var(--violet);
    border-bottom: 3px solid var(--ink);
  }

  tbody td { padding: 6px 12px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
  tbody tr.alt { background: var(--header); }
  tbody tr:hover, tbody tr.active-row { background: var(--gold) !important; color: #000 !important; cursor: pointer; }
  td.num { text-align: center; color: var(--muted); }
  td.lex { font-weight: 600; }
  td.type { font-weight: 700; }
  td.empty { padding: 30px 14px; text-align: center; color: var(--faint); }
  .c-no { width: 64px; text-align: center; }
  .c-sm { width: 72px; text-align: center; }

  /* ---------------- console ---------------- */
  .console-pane {
    flex: none;
    height: 184px;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 3px solid var(--ink);
    box-shadow: var(--shadow);
  }

  .console-tabs {
    display: flex;
    gap: 6px;
  }
  .message-tab {
    padding: 4px 10px;
    border: 2px solid var(--ink);
    background: var(--panel);
    color: var(--muted);
    font-family: inherit;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
  }
  .message-tab[aria-selected="true"] {
    background: var(--header);
    color: var(--ink-strong);
    border-color: var(--ink);
  }
  .message-tab.has-errors { color: var(--crimson); }
  .message-tab:focus-visible {
    outline: 2px solid var(--violet);
    outline-offset: 2px;
  }

  .console-body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 10px 14px;
    background: var(--header);
    font-size: 12.5px;
    line-height: 1.75;
  }
  .log { white-space: pre-wrap; margin-bottom: 4px; padding: 2px 4px; border-radius: 2px; }
  .log.err { color: var(--crimson); font-weight: 700; cursor: pointer; background: rgba(220, 38, 38, 0.1); border-left: 3px solid var(--crimson); }
  .log.err:hover { text-decoration: underline; background: rgba(220, 38, 38, 0.2); }
  .log.ok { color: var(--emerald-text); font-weight: 700; }
  .log.info { color: var(--muted); }

  .badge {
    margin-left: auto;
    padding: 4px 10px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
    background: var(--violet);
    color: var(--ink-strong);
    border: 2px solid var(--ink-strong);
  }
  .badge.idle { background: #EDE7F9; color: var(--royal); border-color: #B9A7E0; }
  .badge.work { background: var(--gold); color: var(--ink-strong); }
  .badge.ok { background: var(--emerald); color: var(--ink-strong); }
  .badge.error { background: var(--crimson); color: #fff; }

  @media (max-width: 900px) {
    .app { height: auto; padding-right: 16px; }
    .workspace { grid-template-columns: 1fr; grid-template-rows: 420px 420px; }
    .nav { flex-wrap: wrap; }
    .tabs { margin-left: 0; }
    .nav-mid-slot { display: none; }
  }
</style>
</head>
<body>
<div class="app">

  <header class="nav">
    <div class="brand">
      <div class="brand-slot"><img src="/LOGO%20TOPLEFT.png" alt="Magi-C Logo"></div>
    </div>
    <div class="nav-mid-slot"><img src="/MIDDLE.png" alt="Magi-C Lexical Analyzer"></div>
    <nav class="tabs">
      <button class="tab" id="themeToggleBtn">🌙 DARK MODE</button>
      <span class="tab active">LEXICAL</span>
    </nav>
  </header>

  <main class="workspace">

    <section class="pane pane-editor">
      <div class="pane-header">
        <div class="actions">
          <button id="clearBtn" class="btn" type="button">CLEAR</button>
          <button id="runBtn" class="btn primary" type="button">&#9654; RUN</button>
        </div>
      </div>
      <div class="editor">
        <div class="gutter" id="gutter">1</div>
        <textarea id="code" aria-label="Source code" spellcheck="false" wrap="off"
                  autocomplete="off" autocapitalize="off" autocorrect="off"></textarea>
      </div>
    </section>

    <section class="pane pane-tokens">
      <div class="table-wrap" id="tableWrap">
        <table>
          <thead>
            <tr>
              <th class="c-no">No.</th>
              <th>Lexeme</th>
              <th>Token Type</th>
              <th class="c-sm">Line</th>
            </tr>
          </thead>
          <tbody id="tokBody"></tbody>
        </table>
      </div>
    </section>

  </main>

  <footer class="console-pane" aria-label="Analysis messages">
    <div class="pane-header">
      <h2>Error Messages:</h2>
      <div class="console-tabs" role="tablist" aria-label="Analysis stages">
        <button class="message-tab" id="lexicalTab" type="button" role="tab"
                aria-selected="true" aria-controls="lexicalPanel" tabindex="0">
          Lexical (<span id="lexicalCount">0</span>)
        </button>
        <button class="message-tab" id="syntaxTab" type="button" role="tab"
                aria-selected="false" aria-controls="syntaxPanel" tabindex="-1">
          Syntax (<span id="syntaxCount">0</span>)
        </button>
      </div>
      <span class="badge idle" id="statusBadge" role="status">IDLE</span>
    </div>
    <div class="console-body" id="consoleEl">
      <section id="lexicalPanel" role="tabpanel" aria-labelledby="lexicalTab" tabindex="0"></section>
      <section id="syntaxPanel" role="tabpanel" aria-labelledby="syntaxTab" tabindex="0" hidden></section>
    </div>
  </footer>

</div>

<script>
(function () {
  "use strict";

  var LINE_H = 22;
  var SAMPLE = {{ sample_program | tojson }};

  var codeEl       = document.getElementById("code");
  var gutterEl     = document.getElementById("gutter");
  var tokBody      = document.getElementById("tokBody");
  var tableWrap    = document.getElementById("tableWrap");
  var consoleEl    = document.getElementById("consoleEl");
  var statusBadge  = document.getElementById("statusBadge");
  var runBtn       = document.getElementById("runBtn");
  var clearBtn     = document.getElementById("clearBtn");
  var themeToggleBtn = document.getElementById("themeToggleBtn");
  var stages = ["lexical", "syntax"];
  var messagePanels = {
    lexical: document.getElementById("lexicalPanel"),
    syntax: document.getElementById("syntaxPanel")
  };
  var analysisVersion = 0;

  var errorLines = {};
  var currentTokens = [];

  // Midnight Dark Mode Toggle + LocalStorage persistence
  if (localStorage.getItem("magi_dark_mode") === "true") {
    document.body.classList.add("dark-mode");
    themeToggleBtn.textContent = "☀️ LIGHT MODE";
  }

  themeToggleBtn.addEventListener("click", function() {
    document.body.classList.toggle("dark-mode");
    var isDark = document.body.classList.contains("dark-mode");
    localStorage.setItem("magi_dark_mode", isDark);
    themeToggleBtn.textContent = isDark ? "☀️ LIGHT MODE" : "🌙 DARK MODE";
  });

  // Token Type Colors for Table Display
  var TYPE_COLORS = {
    IDENTIFIER:     "#4F46E5",
    id:             "#4F46E5",
    aeth_lit:       "#2563EB",
    ess_lit:        "#0284C7",
    insc_lit:       "#D97706",
    COMMENT:        "#8E7BC0",
    EOF:            "#8E7BC0"
  };

  var KEYWORDS = new Set([
    "aether", "aura", "blessed", "cast", "chant", "charge", "circle", "counter",
    "crossroad", "cursed", "darkness", "essence", "fallback", "grimoire",
    "incription", "inscription", "invoke", "manifest", "null", "persist",
    "rune", "remanifest", "scroll", "sealed", "shatter", "spell", "summon", "yield"
  ]);

  function typeColor(type, val) {
    if (KEYWORDS.has(val)) return "#7C3AED";
    if (type_is_symbol(type)) return "#059669";
    if (type in TYPE_COLORS) return TYPE_COLORS[type];
    return "#51308B";
  }

  function type_is_symbol(t) {
    return ["(", ")", "{", "}", "[", "]", "+", "-", "*", "/", "%", "=", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "!", ";", ",", "."].indexOf(t) !== -1 || t.length === 1;
  }

  function displayLexeme(tok) {
    if (tok.type === "EOF") { return "EOF"; }
    return String(tok.value)
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t");
  }

  /* ------------------------- Line Gutter & Scrolling ------------------------- */
  function updateGutter() {
    var lines = codeEl.value.split("\n").length;
    var html = "";
    for (var i = 1; i <= lines; i++) {
      html += '<span class="ln' + (errorLines[i] ? " err" : "") + '">' + i + "</span>";
    }
    gutterEl.innerHTML = html;
    syncScroll();
  }

  function syncScroll() {
    gutterEl.scrollTop = codeEl.scrollTop;
  }

  function scrollToLine(line, col) {
    if (!line || line < 1) { return; }
    codeEl.focus();
    codeEl.scrollTop = Math.max(0, (line - 1) * LINE_H - LINE_H * 2);
    syncScroll();
  }

  /* ------------------------------ Console ------------------------------- */
  function selectStage(stage) {
    stages.forEach(function(name) {
      var selected = name === stage;
      var tab = document.getElementById(name + "Tab");
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      messagePanels[name].hidden = !selected;
    });
    consoleEl.scrollTop = 0;
  }

  function clearConsole() {
    stages.forEach(function(stage) {
      messagePanels[stage].textContent = "";
      document.getElementById(stage + "Count").textContent = "0";
      document.getElementById(stage + "Tab").classList.remove("has-errors");
    });
  }

  function log(stage, kind, text, error) {
    var row = document.createElement("div");
    row.className = "log " + kind;
    row.textContent = text;
    if (error && error.line) {
      row.title = "Click to jump to line " + error.line;
      row.addEventListener("click", function() {
        scrollToLine(error.line, error.column);
      });
    }
    messagePanels[stage].appendChild(row);
  }

  function renderStage(stage, result, tokenCount) {
    var errors = result.errors || [];
    document.getElementById(stage + "Count").textContent = errors.length;
    document.getElementById(stage + "Tab").classList.toggle("has-errors", errors.length > 0);
    errors.forEach(function(error) {
      var text = error.message;
      if (error.line) {
        errorLines[error.line] = true;
        text = "line #" + error.line + ":" + error.column + " - " + text;
      }
      if (error.expected && error.expected.length) {
        text += "\nExpected tokens: " + error.expected.map(function(token) {
          return token === "$" ? "end of input" : "'" + token + "'";
        }).join(", ");
      }
      log(stage, "err", text, error);
    });
    if (stage === "lexical" && errors.length) {
      log(stage, "info", errors.length + (errors.length === 1 ? " error" : " errors") + ". Total Tokens: " + tokenCount);
    }
    if (result.skipped) {
      log(stage, "info", "Fix the lexical errors, then run again to check syntax.");
    } else if (result.ok) {
      var text = stage === "lexical"
        ? "Lexically Successful! 0 Errors. Total Tokens: " + tokenCount
        : "Syntactically Successful! 0 Errors.";
      log(stage, "ok", text);
    }
  }

  function setStatus(label, kind) {
    statusBadge.textContent = label;
    statusBadge.className = "badge " + kind;
  }

  /* ---------------------------- Token Table & Cross-Highlighting ----------------------------- */
  function cell(text, className) {
    var td = document.createElement("td");
    if (className) { td.className = className; }
    td.textContent = text;
    return td;
  }

  function renderTokens(tokens) {
    tokBody.innerHTML = "";
    currentTokens = tokens;

    if (!tokens.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = cell("No tokens — press RUN to scan the source.", "empty");
      emptyCell.colSpan = 4;
      emptyRow.appendChild(emptyCell);
      tokBody.appendChild(emptyRow);
      tableWrap.scrollTop = 0;
      return;
    }

    var frag = document.createDocumentFragment();
    for (var i = 0; i < tokens.length; i++) {
      var tok = tokens[i];
      var tr = document.createElement("tr");
      if (i % 2) { tr.className = "alt"; }
      tr.dataset.index = i;
      tr.appendChild(cell(i + 1, "num"));
      tr.appendChild(cell(displayLexeme(tok), "lex"));
      var typeCell = cell(tok.type, "type");
      typeCell.style.color = typeColor(tok.type, tok.value);
      tr.appendChild(typeCell);
      tr.appendChild(cell(tok.line, "num"));

      // Feature: Cross-Highlighting Token Table Row -> Editor Selection & Scroll
      (function(t, rowEl) {
        rowEl.addEventListener("click", function() {
          document.querySelectorAll("#tokBody tr").forEach(function(r) { r.classList.remove("active-row"); });
          rowEl.classList.add("active-row");
          scrollToLine(t.line, t.column);
          highlightTokenInEditor(t);
        });
      })(tok, tr);

      frag.appendChild(tr);
    }
    tokBody.appendChild(frag);
    tableWrap.scrollTop = 0;
  }

  function highlightTokenInEditor(tok) {
    var text = codeEl.value;
    var lines = text.split("\n");
    if (tok.line > lines.length) return;

    var charIndex = 0;
    for (var i = 0; i < tok.line - 1; i++) {
      charIndex += lines[i].length + 1;
    }
    charIndex += (tok.column - 1);

    codeEl.focus();
    codeEl.setSelectionRange(charIndex, charIndex + String(tok.value).length);
  }

  /* ------------------------------ Results & Analysis ------------------------------- */
  function handleResult(data) {
    var tokens = data.tokens || [];
    errorLines = {};
    clearConsole();
    renderTokens(tokens);
    renderStage("lexical", data.lexical, tokens.length);
    renderStage("syntax", data.syntax, tokens.length);
    updateGutter();
    setStatus(data.ok ? "SUCCESS" : "ERROR", data.ok ? "ok" : "error");

    var failedStage = !data.lexical.ok ? "lexical" : (!data.syntax.ok ? "syntax" : null);
    if (failedStage) {
      selectStage(failedStage);
      var firstError = data[failedStage].errors[0];
      if (firstError) { scrollToLine(firstError.line, firstError.column); }
    }
  }

  function resetAnalysis() {
    // Edits and CLEAR invalidate an in-flight response as well as old diagnostics.
    analysisVersion += 1;
    runBtn.disabled = false;
    runBtn.textContent = "\u25b6 RUN";
    errorLines = {};
    renderTokens([]);
    clearConsole();
    setStatus("IDLE", "idle");
    updateGutter();
  }

  function analyze() {
    var source = codeEl.value;

    if (!source.trim()) {
      resetAnalysis();
      clearConsole();
      log("lexical", "info", "Nothing to analyze. Enter source code and press RUN.");
      log("syntax", "info", "Nothing to analyze. Enter source code and press RUN.");
      return;
    }

    var version = ++analysisVersion;
    runBtn.disabled = true;
    runBtn.textContent = "… RUNNING";
    clearConsole();
    setStatus("WORKING", "work");
    log("lexical", "info", "Scanning " + source.length + " characters…");
    log("syntax", "info", "Waiting for lexical analysis…");

    fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: source })
    })
      .then(function (response) {
        return response.json().then(function(data) {
          if (!response.ok) { throw new Error(data.error ? data.error.message : "Analysis request failed."); }
          return data;
        });
      })
      .then(function(data) {
        if (version === analysisVersion) { handleResult(data); }
      })
      .catch(function (err) {
        if (version !== analysisVersion) { return; }
        clearConsole();
        setStatus("ERROR", "error");
        stages.forEach(function(stage) {
          log(stage, "err", "Request failed — " + err.message);
        });
      })
      .then(function () {
        if (version !== analysisVersion) { return; }
        runBtn.disabled = false;
        runBtn.textContent = "▶ RUN";
      });
  }

  /* ------------------------------ Events -------------------------------- */
  codeEl.addEventListener("input", resetAnalysis);
  codeEl.addEventListener("scroll", syncScroll);
  window.addEventListener("resize", syncScroll);

  codeEl.addEventListener("keydown", function (event) {
    if (event.key === "Tab") {
      event.preventDefault();
      var start = codeEl.selectionStart;
      codeEl.setRangeText("    ", start, codeEl.selectionEnd, "end");
      resetAnalysis();
    } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      analyze();
    }
  });

  runBtn.addEventListener("click", analyze);

  stages.forEach(function(stage) {
    var tab = document.getElementById(stage + "Tab");
    tab.addEventListener("click", function() { selectStage(stage); });
    tab.addEventListener("keydown", function(event) {
      var next;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        next = stage === "lexical" ? "syntax" : "lexical";
      } else if (event.key === "Home") {
        next = "lexical";
      } else if (event.key === "End") {
        next = "syntax";
      } else {
        return;
      }
      event.preventDefault();
      selectStage(next);
      document.getElementById(next + "Tab").focus();
    });
  });

  clearBtn.addEventListener("click", function() {
    codeEl.value = "";
    resetAnalysis();
  });

  /* ------------------------------- Boot --------------------------------- */
  codeEl.value = SAMPLE;
  resetAnalysis();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("magi-C lexical and syntax analyzer running at  http://localhost:5000")
    print("Press CTRL+C to stop.")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
