"""Chat with InDesign — unlimited local agent via Ollama.

A simple conversational agent that connects Ollama (local LLM) to InDesign
via COM. No usage limits, no cloud dependency, runs forever.

Requirements (already installed):
    pip install ollama pywin32

Usage:
    python chat_with_indesign.py
    python chat_with_indesign.py --model qwen3-coder:30b
    python chat_with_indesign.py --model deepseek-r1:32b

Commands inside the chat:
    /status  — check InDesign connection
    /pages   — list pages in active document
    /quit    — exit
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import traceback

# ---------------------------------------------------------------------------
# OneDrive check
# ---------------------------------------------------------------------------

def _is_onedrive_path(path: str) -> bool:
    return "onedrive" in path.lower()

if _is_onedrive_path(os.path.abspath(__file__)):
    print(
        "WARNING: Running from OneDrive. Move to a local path like "
        f"C:\\Users\\{os.environ.get('USERNAME', 'user')}\\indesign-mcp-server\\",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# InDesign COM connection
# ---------------------------------------------------------------------------

PROGIDS = [
    "InDesign.Application",
    "InDesign.Application.CC.2024",
    "InDesign.Application.2024",
    "InDesign.Application.CC.2023",
    "InDesign.Application.2023",
]

JAVASCRIPT = 1246973031
NEVER_INTERACT = 1699640946

_app = None


def get_indesign():
    """Connect to InDesign via COM. Returns the app object or raises."""
    global _app
    if _app is not None:
        try:
            _ = _app.Name
            return _app
        except Exception:
            _app = None

    if platform.system() != "Windows":
        raise RuntimeError("InDesign COM requires Windows.")

    import win32com.client

    for progid in PROGIDS:
        try:
            _app = win32com.client.Dispatch(progid)
            return _app
        except Exception:
            continue
    raise RuntimeError("Could not connect to InDesign. Is it running?")


def run_jsx(script: str) -> str:
    """Execute ExtendScript in InDesign, return result as string."""
    app = get_indesign()
    try:
        app.ScriptPreferences.UserInteractionLevel = NEVER_INTERACT
    except Exception:
        pass
    result = app.DoScript(script, JAVASCRIPT)
    return str(result) if result else "(no return value)"


def get_status() -> str:
    """Get InDesign connection + document status."""
    try:
        app = get_indesign()
        if app.Documents.Count == 0:
            return "Connected to InDesign. No documents open."
        doc = app.ActiveDocument
        return (
            f"Connected to InDesign.\n"
            f"  Document: {doc.Name}\n"
            f"  Pages: {doc.Pages.Count}\n"
            f"  Text frames: {doc.TextFrames.Count}\n"
            f"  Links: {doc.Links.Count}"
        )
    except Exception as e:
        return f"Not connected: {e}"


# ---------------------------------------------------------------------------
# Ollama chat
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an InDesign automation assistant. You help the user control Adobe InDesign on their Windows machine.

You have access to InDesign via a Python COM bridge. When the user asks you to do something in InDesign, you should respond with ExtendScript (JavaScript) code wrapped in ```jsx blocks.

The code will be automatically executed in InDesign. Key facts:
- All measurements use millimeters unless specified otherwise
- Document is US Letter landscape (279.4 x 215.9 mm) with 3.175mm bleed
- Use app.activeDocument to reference the current document
- Pages are 0-indexed: doc.pages.item(0) = page 1
- Return a value at the end of your script to see the result

Available InDesign scripting objects:
- app.activeDocument — the current document
- doc.pages — page collection
- doc.textFrames — all text frames
- doc.rectangles — all rectangles
- doc.links — all placed file links
- page.textFrames.add() — create text frame
- page.rectangles.add() — create rectangle
- rect.place(File("path")) — place image in frame
- rect.fit(FitOptions.FILL_PROPORTIONALLY) — fit image
- doc.exportFile(ExportFormat.PDF_TYPE, File("path"), false, preset) — export PDF

If you need to provide explanation, do so briefly before or after the code block.
If the user's request doesn't need InDesign scripting, just respond normally.
"""


def chat_loop(model: str):
    """Main chat loop with Ollama."""
    try:
        import ollama
    except ImportError:
        print("ERROR: 'ollama' package not installed. Run: pip install ollama")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  InDesign Chat Agent — Model: {model}")
    print(f"  Commands: /status  /pages  /quit")
    print(f"{'='*60}\n")

    # Check InDesign connection at start
    print(f"[system] {get_status()}\n")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() == "/quit":
            print("Bye!")
            break
        elif user_input.lower() == "/status":
            print(f"\n[system] {get_status()}\n")
            continue
        elif user_input.lower() == "/pages":
            try:
                result = run_jsx("""
                var doc = app.activeDocument;
                var r = [];
                for (var i = 0; i < doc.pages.length; i++) {
                    var p = doc.pages[i];
                    r.push((i+1) + ": " + p.textFrames.length + " text, " + p.rectangles.length + " rect");
                }
                r.join("\\n");
                """)
                print(f"\n[pages]\n{result}\n")
            except Exception as e:
                print(f"\n[error] {e}\n")
            continue

        # Send to Ollama
        messages.append({"role": "user", "content": user_input})

        try:
            print("\nAgent: ", end="", flush=True)
            response = ollama.chat(model=model, messages=messages, stream=True)

            full_response = ""
            for chunk in response:
                text = chunk["message"]["content"]
                full_response += text
                print(text, end="", flush=True)
            print("\n")

            messages.append({"role": "assistant", "content": full_response})

            # Auto-execute any JSX code blocks
            jsx_blocks = _extract_jsx(full_response)
            if jsx_blocks:
                for i, jsx in enumerate(jsx_blocks):
                    print(f"[executing JSX block {i+1}/{len(jsx_blocks)}]")
                    try:
                        result = run_jsx(jsx)
                        print(f"[result] {result}\n")
                        messages.append({
                            "role": "user",
                            "content": f"[System: JSX executed successfully. Result: {result}]"
                        })
                    except Exception as e:
                        err = f"[error] {e}"
                        print(f"{err}\n")
                        messages.append({
                            "role": "user",
                            "content": f"[System: JSX execution failed: {e}]"
                        })

        except Exception as e:
            print(f"\n[ollama error] {e}\n")
            if "connection" in str(e).lower():
                print("Is Ollama running? Start it with: ollama serve")
            messages.pop()  # Remove failed user message


def _extract_jsx(text: str) -> list[str]:
    """Extract JSX/JavaScript code blocks from LLM response."""
    blocks = []
    markers = ["```jsx", "```javascript", "```extendscript", "```js"]

    for marker in markers:
        remaining = text
        while marker in remaining:
            start = remaining.index(marker) + len(marker)
            remaining = remaining[start:]
            if "```" in remaining:
                end = remaining.index("```")
                code = remaining[:end].strip()
                if code:
                    blocks.append(code)
                remaining = remaining[end + 3:]
            else:
                break

    return blocks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chat with InDesign via Ollama")
    parser.add_argument(
        "--model", "-m",
        default="qwen3-coder:30b",
        help="Ollama model to use (default: qwen3-coder:30b)"
    )
    args = parser.parse_args()
    chat_loop(args.model)
