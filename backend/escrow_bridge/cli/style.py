# escrow_bridge/cli/style.py
"""
Unified CLI styling utilities for Escrow Bridge.
Clean, readable terminal output following modern CLI conventions.
"""

from rich.console import Console
from rich.panel import Panel
from rich.progress import SpinnerColumn, TextColumn, TimeElapsedColumn, Progress
from rich.json import JSON
from rich.pretty import Pretty
from rich.table import Table
from rich.text import Text
import os
import sys

# ─────────────────────────────────────────────
# Console instance
# ─────────────────────────────────────────────

# Auto-detect if we need ASCII mode based on console encoding
_needs_ascii = False
if sys.platform == "win32":
    try:
        encoding = sys.stdout.encoding or "utf-8"
        # Test if console supports Unicode arrow
        "→".encode(encoding)
    except (UnicodeEncodeError, AttributeError):
        _needs_ascii = True

console = Console(highlight=False, soft_wrap=True, legacy_windows=False)

# ─────────────────────────────────────────────
# Color map (minimal, purposeful)
# ─────────────────────────────────────────────
color_map = {
    "success": "green",
    "warn": "yellow",
    "error": "red",
    "info": "white",
    "highlight": "cyan",
    "title": "bold cyan",
}

# ─────────────────────────────────────────────
# Symbol map (with ASCII fallback)
# ─────────────────────────────────────────────
symbol_map = {
    "success": "✓",
    "warn": "⚠",
    "error": "✗",
    "info": "ℹ",
    "arrow": "→",
    "pending": "…",
    "dot": "•",
    "separator": "─",
}

TEXTMODE = bool(os.environ.get("ESCROW_BRIDGE_TEXTMODE", "").lower() in ("1", "true", "yes")) or _needs_ascii
if TEXTMODE:
    symbol_map.update({
        "success": "OK",
        "warn": "!",
        "error": "X",
        "info": "i",
        "arrow": "->",
        "pending": "...",
        "dot": "*",
        "separator": "-",
    })

# ─────────────────────────────────────────────
# Status printing helper
# ─────────────────────────────────────────────
def print_status(
    message: str,
    level: str = "info",
    *,
    bold: bool = False,
    italic: bool = False,
    prefix: bool = True,
    spacing: bool = False
):
    """
    Print a concise status line.
    Mirrors Stripe/Heroku CLI logs: simple color, optional symbol, minimal markup.
    """
    color = color_map.get(level, "white")
    symbol = f"{symbol_map.get(level, '')} " if prefix else ""

    # Keep markup minimal
    markup = message
    if bold:
        markup = f"[bold]{markup}[/bold]"
    elif italic:
        markup = f"[italic]{markup}[/italic]"

    console.print(f"[{color}]{symbol}{markup}[/{color}]")
    if spacing:
        console.print()  # blank line between sections

# ─────────────────────────────────────────────
# Panel helper
# ─────────────────────────────────────────────
def print_panel(
    body: str,
    tone: str = "info",
    *,
    accent_first_line: bool = True,
    borders: bool = False,
):
    """
    Print a structured block of text with minimal framing.
    First line gets subtle color accent; body remains plain.
    """
    colors = {
        "info": "cyan",
        "success": "green",
        "warn": "yellow",
        "error": "red",
    }
    color = colors.get(tone, "white")

    lines = [ln.rstrip() for ln in body.strip().splitlines() if ln.strip()]
    if not lines:
        return

    if borders:
        console.print("\n" + "─" * console.width)

    if accent_first_line:
        # Print first line with accent color (bold)
        console.print(f"[bold {color}]{lines[0]}[/bold {color}]")
        # Print remaining lines with Rich markup support
        for line in lines[1:]:
            console.print(line)
    else:
        # Print all lines with Rich markup support
        for line in lines:
            console.print(line)

    if borders:
        console.print("─" * console.width + "\n")


# ─────────────────────────────────────────────
# Progress context
# ─────────────────────────────────────────────
def progress_bar(description: str = "Working..."):
    """Return a styled progress spinner context manager."""
    return Progress(
        SpinnerColumn(style=color_map["highlight"]),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    )

# ─────────────────────────────────────────────
# JSON and Pretty Printers
# ─────────────────────────────────────────────
def print_json(data, indent: int = 2):
    """Render a JSON or dict object in consistent Rich style."""
    console.print()  # spacing
    try:
        console.print(JSON.from_data(data, indent=indent))
    except Exception:
        console.print(Pretty(data))
    console.print()  # spacing

def print_table(headers, rows, title=None):
    """Render Rich tables with auto styling and minimal color."""
    console.print()  # spacing
    table = Table(show_header=True, header_style="bold cyan")
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*[str(c) for c in row])
    if title:
        table.title = f"[bold cyan]{title}[/bold cyan]"
    console.print(table)
    console.print()  # spacing
