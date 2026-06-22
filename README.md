# Production Automation

Local agent-driven automation for Adobe Creative Suite and other production tools. Designed to run on Windows with local LLMs (Ollama) for unlimited, no-cloud-dependency automation.

## Structure

```
production-automation/
├── indesign/           # InDesign automation
│   ├── mcp_server/     # MCP server (Claude Code + agents)
│   ├── chat_agent/     # Ollama chat interface
│   ├── jsx_templates/  # Reusable ExtendScript templates
│   └── handoff/        # Handoff package builder
├── photoshop/          # (future) Photoshop automation
├── illustrator/        # (future) Illustrator automation
├── shared/             # Cross-app utilities (OneDrive check, path helpers)
└── scripts/            # Setup & launcher scripts
```

## Quick Start (Windows)

```powershell
# Clone to a LOCAL path (not OneDrive!)
cd C:\Users\toddl
git clone https://github.com/brookehoward2008-droid/production-automation.git
cd production-automation

# Install dependencies
pip install ollama pywin32 mcp pillow

# Chat with InDesign (unlimited, local)
python indesign\chat_agent\chat_with_indesign.py --model qwen3-coder:30b

# Or use the MCP server with Claude Code
python indesign\mcp_server\indesign_mcp_server.py
```

## Requirements

- Windows 10/11
- Adobe InDesign 2021+ (installed, licensed, running)
- Python 3.9+ with pywin32
- Ollama (for local LLM chat agent)

## OneDrive Warning

This repo includes built-in OneDrive detection. InDesign files saved to OneDrive get corrupted by sync. All output defaults to `C:\Users\<you>\InDesign-Automation-Output\` (local disk).

## Adding More Programs

Each Adobe app gets its own folder. The `shared/` directory has utilities that work across all apps (path validation, COM connection helpers, OneDrive checking). To add Photoshop automation, create scripts in `photoshop/` following the same pattern as `indesign/`.
