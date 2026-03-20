# Ollama File System Bridge

Un progetto Python che funge da strato intermediario tra l'inferenza di Ollama e il file system, permettendo agli LLM di leggere e scrivere file tramite comandi JSON.

> **Scopo del progetto**: Fornire "le mani" agli LLM che non supportano tooling nativo (function calling), permettendo loro di creare, modificare e analizzare progetti software autonomamente.

## 🎯 Cosa fa

Questo bridge permette agli LLM di:
- 🏗️ **Creare progetti da zero** (struttura completa con codice)
- 🔧 **Fixare codice esistente** (legge file, identifica bug, applica correzioni)
- 🔍 **Effettuare code review** (analisi statica del codice)
- ⚡ **Ottimizzare codice** (refactoring automatico)
- 📊 **Analizzare progetti** (reverse engineering con documentazione automatica)
- 📝 **Tracciare modifiche** (claude.md come unico file di storico)

## 🏗️ Architettura

```
┌─────────────────────────────────────────────────────────────────┐
│  User Input                                                     │
│  (CLI / GUI / TUI)                                              │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ollama LLM (qwen2.5-codershellBot)                             │
│  System Prompt: JSON commands only                              │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  JSON Commands → Command Parser → File Operations               │
│  {"cmd1": "cat file.py"}                                        │
│  {"cmd2": "cat << 'EOF' > file.py\n...\nEOF"}                   │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  File System                                                    │
│  - Lettura/scrittura file                                       │
│  - Esecuzione comandi shell                                     │
│  - Fix automatico sintassi                                      │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  claude.md (unico file di tracciamento)                         │
│  - [v] Fix: descrizione (data)                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 Requisiti

### Sistema
- **Python 3.8+**
- **Ollama** installato e configurato
- **Modello LLM** compatibile (es: qwen2.5-codershellBot:latest)

### GUI (opzionale)
```bash
# Su Debian/Ubuntu
sudo apt install python3-tk
```

## 🚀 Installazione

```bash
cd my_claude_code

# Installa dipendenze Python
pip3 install -r requirements.txt

# Se vuoi la GUI, installa tkinter a livello di sistema
sudo apt install python3-tk
```

## ⚙️ Configurazione

Modifica `config.json`:

```json
{
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-codershellBot:latest",
        "timeout": 600
    },
    "working_directory": ".",
    "max_tokens": 4096,
    "safety": {
        "require_confirmation_for_destructive": true,
        "allowed_directories": []
    }
}
```

> **Nota:** Il modello in `config.json` è un default. Puoi cambiarlo a runtime con `/model <nome>`.

## 💻 Utilizzo

### 1. Avvia Ollama
```bash
ollama serve
```

### 2. Scarica un modello compatibile
```bash
# Modello consigliato (con system prompt per JSON commands)
ollama pull qwen2.5-coder:14b-instruct-q4_0

# Oppure usa il tuo modello custom
ollama show qwen2.5-codershellBot:latest
```

### 3. Avvia il Bridge

**Modalità CLI (terminale - default):**
```bash
python3 main.py
```

**Modalità GUI (finestra grafica):**
```bash
python3 main.py --gui
```

**Modalità TUI (chat testuale con Textual):**
```bash
python3 main.py --chat
```

**Prompt singolo:**
```bash
python3 main.py -p "crea un gioco del tris in /path/proj"
```

## 🎨 Interfacce

### CLI (Terminale)
```
╔═══════════════════════════════════════════════════════════╗
║   OLLAMA FILE SYSTEM BRIDGE                               ║
╚═══════════════════════════════════════════════════════════╝

✓ Ollama connesso
✓ Modelli trovati: 5
✓ Sessione: session_1_20260312_153907

Comandi: /help /fix /new /reverse /model /safe /auto /test /context /exit
```

### GUI (Tkinter)
- Finestra grafica con tema scuro
- Chat con colori sintassi
- Barra di stato (connessione, modello, sessione)
- Menu per impostazioni e aiuto
- Supporto multi-sessione

### TUI (Textual)
- Input di testo senza caratteri strani
- Navigazione con frecce
- Shortcut: Ctrl+M (invia), Ctrl+L (pulisci), Ctrl+Q (esci)

## 🧩 Comandi

### Modalità di Lavoro

| Comando | Descrizione | Comportamento |
|---------|-------------|---------------|
| `/fix` | **Modalità FIX** | Legge file esistenti, non crea README.md, aggiorna claude.md con i fix |
| `/new` | **Modalità NEW PROJECT** | Crea progetti da zero (claude.md + codice) |
| `/reverse [path]` | **Reverse Engineering** | Analizza progetto e genera DOCUMENTAZIONE.md |

### Gestione

| Comando | Descrizione |
|---------|-------------|
| `/help` | Mostra aiuto completo |
| `/model <nome>` | Cambia modello LLM |
| `/safe` | Toggle safety (ON/OFF) |
| `/auto` | Auto-continue (ON/OFF) |
| `/test` | Auto-test dopo fix (ON/OFF) |
| `/context` | Mostra claude.md corrente |
| `/exit` | Esci dall'applicazione |

### Esempi di utilizzo

```bash
# 1. Fix di codice esistente
/fix
fixa il gioco del tris che non parte quando clicco su "New Game"

# Il bridge:
# - Legge index.html, tris.js
# - Identifica il bug
# - Fixa solo le parti necessarie
# - Aggiorna claude.md: "- [v] Fix: New Game non funzionante (2026-03-12)"

# 2. Creazione nuovo progetto
/new
crea un gestionale per biblioteca in /home/vik/Documenti/progetti/biblioteca

# Il bridge:
# - Crea struttura directory
# - Crea claude.md con todo-list
# - Crea file Python/HTML/JS
# - Verifica sintassi

# 3. Reverse engineering
/reverse /home/vik/Documenti/progetti/vecchio-progetto

# Il bridge:
# - Legge tutti i file (.py, .js, .html, ecc.)
# - Genera DOCUMENTAZIONE.md con:
#   - Panoramica funzionale
#   - Struttura file
#   - Tecnologie usate
#   - API e funzioni principali
```

## 📝 Formato Comandi JSON

Il LLM risponde **SOLO** con JSON (system prompt in Ollama):

```json
{
  "cmd1": "mkdir -p /path/proj",
  "cmd2": "cat << 'EOF' > /path/proj/claude.md\n# Progetto\nDescrizione...\nEOF",
  "cmd3": "cat << 'EOF' > /path/proj/main.py\ndef main():\n    pass\nEOF"
}
```

| Operazione | Comando |
|------------|---------|
| Lettura file | `{"cmd1": "cat file.txt"}` |
| Scrittura file | `{"cmd1": "cat << 'EOF' > file.txt\ncontenuto\nEOF"}` |
| Directory | `{"cmd1": "mkdir -p path"}` |
| Lista file | `{"cmd1": "ls -la"}` |
| Esecuzione | `{"cmd1": "python3 test.py"}` |

## 🔧 Parser JSON - Cosa gestisce

Il `CommandParser` (`src/command_parser.py`) estrae e ripara automaticamente i comandi JSON dalle risposte LLM:

### Estrazione comandi

| Caso | Descrizione |
|------|-------------|
| ✅ **JSON in code block** | ` ```json {...} ``` ` - priorità massima |
| ✅ **JSON inline** | `{"cmd1": "..."}` nel testo |
| ✅ **JSON troncato** | Mancanza chiusura graffe |
| ✅ **Thinking tags** | Rimuove `<think>...</think>` |

### Fix automatici

| Problema | Fix applicato |
|----------|---------------|
| **Stringhe non chiuse** | Chiude automaticamente prima del prossimo `cmdN` |
| **Newline non escapeati** | Converte `\n` reali in `\\n` dentro stringhe |
| **Tab non escapeati** | Converte `\t` reali in `\\t` |
| **Virgolette extra** | Rimuove `"` finali non escapeate |
| **EOF malformato** | Corregge `'EOF"` → `'EOF'` negli heredoc |
| **Escape PowerShell** | Fixa backtick, parentesi quadre, pipe |
| **Virgole extra** | Rimuove `,` dopo chiusura stringhe |
| **Estrazione manuale** | Regex fallback per JSON irrecuperabili |

### Formato comandi supportati

```json
// Formato nuovo (multi-comando)
{"cmd1": "mkdir proj", "cmd2": "cat << 'EOF' > file\ncontent\nEOF"}

// Formato legacy (singolo)
{"command": "mkdir proj"}
```

### Sicurezza

- **Pattern bloccati**: `rm -rf /`, `sudo rm`, `mkfs`, `dd if=`
- **Validazione heredoc**: controlla sintassi PowerShell `cat << 'EOF'`
- **Intercept scrittura .md**: usa Python invece di PowerShell per evitare problemi con apici, liste, trattini

## 🔧 Fix Automatico

Il bridge include fix automatico per:

- **Python**: sintassi print(), stringhe, parentesi, backslash
- **Java**: punto e virgola, System.out.println, parentesi
- **JavaScript**: escape characters, sintassi base
- **Shell**: escape characters

I fix vengono applicati automaticamente dopo l'esecuzione dei comandi.

## 📁 Struttura Progetto

```
my_claude_code/
├── main.py                 # Entry point CLI/GUI/TUI
├── config.json             # Configurazione Ollama
├── requirements.txt        # Dipendenze Python
├── README.md               # Questo file
├── .ollama_bridge_state.json  # Stato (modello, impostazioni)
├── src/
│   ├── ollama_client.py    # Client Ollama API
│   ├── file_operations.py  # Operazioni file system
│   ├── command_parser.py   # Parser JSON commands
│   ├── session_manager.py  # Gestione sessioni
│   ├── system_prompt.py    # (Placeholder, system è in Ollama)
│   ├── chat_ui.py          # TUI (Textual)
│   └── gui.py              # GUI (Tkinter)
├── logs/
│   ├── ollama_*.log        # Log esecuzioni
│   └── requests/           # Log request/response JSON
├── sessions/               # Sessioni salvate
└── examples/
    └── usage_examples.md   # Esempi avanzati
```

## ⚠️ Sicurezza

- **Safety mode**: richiede conferma per comandi distruttivi (`rm`, `rmdir`, ecc.)
- **Pattern bloccati**: comandi pericolosi vengono rifiutati
- **Working directory**: limitabile in `config.json`
- **Allowed directories**: whitelist opzionale

## 📊 Log e Debug

Tutte le esecuzioni vengono loggate in:

- `logs/ollama_*.log` - Log generali
- `logs/requests/*.json` - Request/response JSON completi

Per visualizzare l'ultimo log:
```bash
tail -f logs/ollama_*.log
```

## ✅ Task Tracking

### Completati

| ID | Task | Stato |
|----|------|-------|
| 1 | Project Structure | ✅ |
| 2 | Ollama Client | ✅ |
| 3 | System Prompt (in Ollama) | ✅ |
| 4 | Command Parser | ✅ |
| 5 | Session Manager | ✅ |
| 6 | CLI Interface | ✅ |
| 7 | Configuration | ✅ |
| 8 | Examples | ✅ |
| 9 | UI (TUI + GUI) | ✅ |
| 10 | Modello a runtime | ✅ |
| 11 | **Modalità /fix** | ✅ |
| 12 | **Modalità /new** | ✅ |
| 13 | **Modalità /reverse** | ✅ |
| 14 | **Fix automatico sintassi** | ✅ |
| 15 | **claude.md unico file** | ✅ |

### Futuri

| ID | Task |
|----|------|
| 16 | Multi-file batch operations |
| 17 | Web interface |
| 18 | Async support |
| 19 | Tool calling nativo (se supportato) |

## ⚙️ Modelfile Ollama

Il system prompt è nel modelfile di Ollama, non nel bridge.

Esempio modelfile:
```dockerfile
FROM qwen2.5-coder:14b-instruct-q4_0

SYSTEM """
You are an assistant that generates EXCLUSIVELY shell commands in JSON format.
No additional text, no explanations, no markdown.

ABSOLUTE RULES:
1. Reply ONLY with a valid JSON object
2. Every action is a "cmd" field with the exact shell command
3. To create files always use: cat << 'EOF' > path/file \n content \n EOF
4. For directories use: mkdir -p
5. Code inside files must be COMPLETE and WORKING
6. Zero comments outside the JSON
7. If creating a project: first create folders, then claude.md with description, then source files
8. Code must have NO duplicated words or tokens
9. Use claude.md for project tracking, NOT README.md
"""

PARAMETER num_gpu 96
PARAMETER num_thread 8
```

Per creare un modello custom:
```bash
ollama create qwen2.5-codershellBot -f Modelfile
```

## 📄 License

MIT License

## 🤝 Contributing

1. Fork il progetto
2. Crea un branch per la feature
3. Commit con messaggi descrittivi
4. Push e apri una Pull Request

---

**Nota**: Questo progetto è ottimizzato per modelli locali Ollama senza supporto nativo per function calling. Per modelli con tooling (Claude, GPT), usare le API native.
