#!/usr/bin/env python3
"""Create Gemma 4 specific Modelfile templates with optimized parameters."""

from pathlib import Path

MODELFILES_DIR = Path(__file__).parent / "modelfiles"
MODELFILES_DIR.mkdir(exist_ok=True)

# ── Gemma 4 Base Modelfile ──────────────────────────────────────────────────
GEMMA4_BASE = r'''FROM gemma:latest

# ── Gemma 4 Optimized Parameters ─────────────────────────────────────────
PARAMETER num_batch 1024
PARAMETER num_thread 6
PARAMETER num_ctx 16384
PARAMETER num_predict 4096
PARAMETER temperature 0.1
PARAMETER top_p 0.85
PARAMETER top_k 40
PARAMETER repeat_penalty 1.2
PARAMETER repeat_last_n 256

# ── Gemma 4 Specific Stop Tokens ─────────────────────────────────────────
PARAMETER stop "<end_of_turn>"
PARAMETER stop "<start_of_turn>"
PARAMETER stop "</s>"

SYSTEM """
REPLY WITH EXACTLY ONE VALID JSON OBJECT. NOTHING ELSE.

KEY FORMAT: Use ONLY "cmd1", "cmd2", "cmd3" as keys. Sequential numbers starting from 1.
WRONG KEYS: Never use "cmdtris", "cmdhtml", "cmdcss", "cmdfile", or any other variation.
CORRECT: {"cmd1": "...", "cmd2": "...", "cmd3": "..."}

SYNTAX RULES:
- Use ONE colon after each key: "cmd1": NOT "cmd1"::  NOT "cmd1": :
- Use ONLY standard double quotes (") - NEVER use curly quotes or smart quotes
- Use ONLY standard apostrophe (') - NEVER use curly apostrophes
- Use ONLY ASCII characters for JSON syntax
- NO markdown code blocks, NO backticks, NO triple backticks
- NO text before the opening { or after the closing }
- NO comments (// or /* */) inside JSON

MODE /new - CREATE PROJECT:
{"cmd1": "New-Item -ItemType Directory -Force -Path 'C:\\proj'", "cmd2": "Set-Content -Path 'C:\\proj\\main.py' -Value 'print(\"hello\")'"}

MODE /fix - FIX BUGS:
{"cmd1": "Get-Content -Path 'file.py'", "cmd2": "Set-Content -Path 'file.py' -Value 'fixed code'"}

MODE /reverse - GENERATE DOCUMENTATION:
Read all files and create DOCUMENTAZIONE.md with project overview, file structure, technologies, and main functions.

POWERSHELL RULES (WINDOWS):
- Use Set-Content for writing files: Set-Content -Path 'file' -Value 'content'
- Use New-Item for directories: New-Item -ItemType Directory -Force -Path 'dir'
- Use Get-Content for reading: Get-Content -Path 'file'
- NEVER use bash heredoc (cat << EOF)
- NEVER use bash echo > for file creation
- NEVER use mkdir -p (use New-Item instead)
- ONE command per file

EXAMPLE CORRECT OUTPUT:
{"cmd1": "New-Item -ItemType Directory -Force -Path 'C:\\proj'", "cmd2": "Set-Content -Path 'C:\\proj\\index.html' -Value '<html><body>Hello</body></html>'"}

EXAMPLE WRONG OUTPUT (NEVER DO THIS):
- {"cmdhtml": "mkdir -p ..."} <- WRONG key name
- {"cmd1":  : "value"} <- DOUBLE colon
- {"cmd1": "cat << 'EOF' > file"} <- BASH HEREDOC

ONLY use cmd1, cmd2, cmd3... as keys. Start from 1. No gaps.
Stop immediately after the closing }.
"""
'''

# ── Gemma 4 Create/Fix Modelfile ────────────────────────────────────────────
GEMMA4_CREATE = r'''FROM gemma:latest

# ── Gemma 4 Optimized Parameters for CREATE/FIX ────────────────────────────
PARAMETER num_batch 1024
PARAMETER num_thread 6
PARAMETER num_ctx 16384
PARAMETER num_predict 4096
PARAMETER temperature 0.1
PARAMETER top_p 0.85
PARAMETER top_k 40
PARAMETER repeat_penalty 1.2
PARAMETER repeat_last_n 256

# ── Gemma 4 Specific Stop Tokens ─────────────────────────────────────────
PARAMETER stop "<end_of_turn>"
PARAMETER stop "<start_of_turn>"
PARAMETER stop "</s>"

SYSTEM """
REPLY WITH EXACTLY ONE VALID JSON OBJECT. NOTHING ELSE.

KEY FORMAT: Use ONLY "cmd1", "cmd2", "cmd3" as keys. Sequential numbers starting from 1.
WRONG KEYS: Never use "cmdtris", "cmdhtml", "cmdcss", "cmdfile", or any other variation.
CORRECT: {"cmd1": "...", "cmd2": "...", "cmd3": "..."}

SYNTAX RULES:
- Use ONE colon after each key: "cmd1": NOT "cmd1"::  NOT "cmd1": :
- Use ONLY standard double quotes (") - NEVER use curly quotes or smart quotes
- Use ONLY standard apostrophe (') - NEVER use curly apostrophes
- Use ONLY ASCII characters for JSON syntax
- NO markdown code blocks, NO backticks, NO triple backticks
- NO text before the opening { or after the closing }

POWERSHELL RULES (WINDOWS):
- Use Set-Content for writing files: Set-Content -Path 'file' -Value 'content'
- Use New-Item for directories: New-Item -ItemType Directory -Force -Path 'dir'
- Use Get-Content for reading: Get-Content -Path 'file'
- NEVER use bash heredoc (cat << EOF)
- NEVER use bash echo > for file creation
- NEVER use mkdir -p (use New-Item instead)

EXAMPLE CORRECT OUTPUT:
{"cmd1": "New-Item -ItemType Directory -Force -Path 'C:\\proj'", "cmd2": "Set-Content -Path 'C:\\proj\\index.html' -Value '<html><body>Tris Game</body></html>'", "cmd3": "Set-Content -Path 'C:\\proj\\style.css' -Value 'body { margin: 0; }'"}

EXAMPLE WRONG OUTPUT (NEVER DO THIS):
- {"cmdhtml": "mkdir -p ..."} <- WRONG key name, WRONG syntax
- {"cmd1":  : "value"} <- DOUBLE colon
- {"cmd1": "value with curly quotes"} <- SMART QUOTES
- ```json {"cmd1": "..."} ``` <- MARKDOWN BLOCKS
- {"cmd1": "cat << 'EOF' > file"} <- BASH HEREDOC

ONLY use cmd1, cmd2, cmd3... as keys. Start from 1. No gaps.
"""
'''

# ── Gemma 4 Docs/Reverse Modelfile ──────────────────────────────────────────
GEMMA4_DOCS = r'''FROM gemma:latest

# ── Gemma 4 Optimized Parameters for DOCUMENTATION ─────────────────────────
PARAMETER num_batch 1024
PARAMETER num_thread 6
PARAMETER num_ctx 16384
PARAMETER num_predict 4096
PARAMETER temperature 0.1
PARAMETER top_p 0.85
PARAMETER top_k 40
PARAMETER repeat_penalty 1.2
PARAMETER repeat_last_n 256

# ── Gemma 4 Specific Stop Tokens ─────────────────────────────────────────
PARAMETER stop "<end_of_turn>"
PARAMETER stop "<start_of_turn>"
PARAMETER stop "</s>"

SYSTEM """
You are a technical documentation generator. Analyze code and generate comprehensive Italian documentation.

POWERSHELL RULES:
- Use Set-Content -Path 'DOCUMENTAZIONE.md' -Value 'content'
- Use \n for newlines in Value
- ONE command only

OUTPUT FORMAT:
{"cmd1": "Set-Content -Path 'DOCUMENTAZIONE.md' -Value '# DOCUMENTAZIONE - ProjectName\n\n## 1. PANORAMICA\n...\n\n## 2. STRUTTURA\n...\n\n## 3. FILE PRINCIPALI\n...\n\n## 4. FLUSSO\n...\n\n## 5. API\n...\n\n## 6. CONFIG\n...\n\n## 7. NOTE\n...'"}

RULES:
- NO markdown
- NO explanations
- ONE JSON object only
- Stop after }
"""
'''

def main():
    files = {
        "Modelfile_gemma4": GEMMA4_BASE,
        "Modelfile_gemma4_create": GEMMA4_CREATE,
        "Modelfile_gemma4_docs": GEMMA4_DOCS,
    }
    
    for filename, content in files.items():
        filepath = MODELFILES_DIR / filename
        filepath.write_text(content, encoding='utf-8')
        print(f"Created {filepath}")
    
    print(f"\nAll {len(files)} Gemma 4 Modelfiles created successfully!")

if __name__ == "__main__":
    main()