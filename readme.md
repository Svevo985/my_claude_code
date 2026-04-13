# Ollama File System Bridge

Un progetto Python che funge da strato intermediario tra l'inferenza di Ollama e il file system, permettendo agli LLM di leggere, scrivere ed eseguire file tramite comandi JSON.

> **Scopo del progetto**: Fornire "le mani" agli LLM che non supportano tooling nativo (function calling), permettendo loro di creare, modificare e analizzare progetti software autonomamente.

## 🎯 Cosa fa

Questo bridge permette agli LLM di:
- 🏗️ **Creare progetti da zero** (struttura completa con codice)
- 🔧 **Fixare codice esistente** (legge file, identifica bug, applica correzioni)
- 📚 **Resume di lavoro interrotto** (riprende da dove si era fermato)
- 🔍 **Effettuare reverse engineering** (analisi con documentazione automatica)
- 📝 **Tracciare modifiche** (readme.md come unico file di storico)

## 🏗️ Architettura

```
┌─────────────────────────────────────────────────────────────────┐
│  User Input                                                     │
│  (CLI / GUI / TUI)                                              │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Bridge (main.py)                                               │
│  - Gestione modalità (/new, /fix, /reverse, /resume)            │
│  - Session lifecycle & model switching automatico               │
│  - Loop iterativo (fino a 8x per richiesta)                     │
│  - Truncated response handling                                  │
│  - Auto-fix sintassi post-esecuzione                            │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ollama LLM (modello specializzato in base alla modalità)       │
│  /new, /fix → shellbot-create:latest                            │
│  /reverse  → shellbot-docs:latest                               │
│  System Prompt: JSON commands only (Modelfile)                  │
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
│  - Fix automatico sintassi (.py, .java, .js, .sh)              │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  readme.md (unico file di tracciamento)                         │
│  - Implementation Checklist                                     │
│  - Fix History table                                            │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 Requisiti

### Sistema
- **Python 3.8+**
- **Ollama** installato e configurato
- **Modello LLM** compatibile (es: shellbot specializzati)

### GUI (opzionale)
```bash
# Su Debian/Ubuntu
sudo apt install python3-tk
```

## 🚀 Installazione

```bash
cd my_claude_code

# Installa dipendenze Python
pip install -r requirements.txt
```

## ⚙️ Configurazione

Il bridge usa **hardcoded defaults** se non trova `config.json`:

```json
{
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "shellbot:latest",
        "timeout": 1800
    }
}
```

> **Nota:** Il modello in `config.json` è un default. Il bridge **cambia automaticamente modello** in base alla modalità attiva (vedi 🔄 Model Switching).

## 💻 Utilizzo

### 1. Avvia Ollama
```bash
ollama serve
```

### 2. Configura i modelli specializzati

Il progetto usa **modelli specializzati** per ogni modalità (vedi `modelfiles/`):

```bash
# Crea il modello base shellbot
ollama create shellbot -f Modelfile

# Crea i modelli specializzati (Windows/PowerShell)
ollama create shellbot-create -f modelfiles/Modelfile_windows_create
ollama create shellbot-docs -f modelfiles/Modelfile_windows_docs

# Oppure per Gemma 4
ollama create gemma4-shellbot-create -f modelfiles/Modelfile_gemma4_create
ollama create gemma4-shellbot-docs -f modelfiles/Modelfile_gemma4_docs
```

### 3. Avvia il Bridge

**Modalità CLI (terminale - default):**
```bash
python main.py
```

**Modalità GUI (finestra grafica):**
```bash
python main.py --gui
```

**Modalità TUI (chat testuale con Textual):**
```bash
python main.py --chat
```

**Prompt singolo:**
```bash
python main.py -p "crea un gioco del tris in /path/proj"
```

**Rigenera modelli shellbot:**
```bash
python main.py --rebuild-shellbot
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

Comandi: /help /fix /new /reverse /resume /model /safe /auto /test /context /exit
```

### GUI (Tkinter)
- Finestra grafica con tema scuro (VS Code-inspired)
- Chat con colori sintassi
- Thinking animation (spinner)
- Commands panel con bottoni per /fix, /new, /reverse
- Barra di stato (connessione, modello, sessione, path)
- Supporto multi-sessione
- Stop button per interrompere inferenza

### TUI (Textual)
- Terminal UI con Textual framework
- RichLog per output stilizzato
- Shortcut: Ctrl+M (invia), Ctrl+L (pulisci), Ctrl+Q (esci)

## 🧩 Comandi

### Modalità di Lavoro

| Comando | Descrizione | Modello Usato | Comportamento |
|---------|-------------|---------------|---------------|
| `/new` | **Nuovo progetto** | shellbot-create | Crea da zero (readme.md + codice + checklist) |
| `/fix` | **Fix/Add feature** | shellbot-create | Legge file, fixa, aggiorna Fix History |
| `/reverse [path]` | **Reverse Engineering** | shellbot-docs | Analizza progetto, genera DOCUMENTAZIONE.md |
| `/resume [path]` | **Resume interrotto** | shellbot-create | Riprende da checklist, crea file mancanti |

### Gestione

| Comando | Descrizione |
|---------|-------------|
| `/help` | Mostra aiuto completo |
| `/model <nome>` | Cambia modello LLM |
| `/safe` | Toggle safety (ON/OFF) |
| `/auto` | Auto-continue (ON/OFF) |
| `/test` | Auto-test dopo fix (ON/OFF) |
| `/context` | Mostra readme.md corrente |
| `/rebuild` | Rigenera modelli shellbot da Modelfile |
| `/exit` | Esci dall'applicazione |

### Esempi di utilizzo

```bash
# 1. Creazione nuovo progetto
/new
crea un gestionale per biblioteca in /home/vik/Documenti/progetti/biblioteca

# Il bridge:
# - Crea struttura directory
# - Crea readme.md con todo-list e file plan
# - Crea file Python/HTML/JS (max 200 linee ciascuno)
# - Aggiorna checklist in readme.md
# - Verifica sintassi e avvia il progetto

# 2. Fix di codice esistente
/fix
fixa il gioco del tris che non parte quando clicco su "New Game"

# Il bridge:
# - Legge readme.md (o file sorgenti se manca)
# - Legge i file rilevanti
# - Fixa solo le parti necessarie
# - Aggiorna Fix History in readme.md

# 3. Resume lavoro interrotto
/resume /home/vik/Documenti/progetti/biblioteca

# Il bridge:
# - Legge readme.md per vedere checklist
# - Crea SOLO i file ancora marcati [ ]
# - Aggiorna checklist con [x]

# 4. Reverse engineering
/reverse /home/vik/Documenti/progetti/vecchio-progetto

# Il bridge:
# - Legge tutti i file (.py, .js, .html, ecc.)
# - Genera DOCUMENTAZIONE.md con:
#   - Panoramica funzionale
#   - Struttura file (ASCII tree)
#   - Tecnologie usate
#   - API e funzioni principali
#   - Flusso di esecuzione
```

## 🔄 Model Switching Automatico

Il bridge **cambia automaticamente modello** in base alla modalità attiva:

```
Modalità /new o /fix  →  shellbot-create:latest
Modalità /reverse     →  shellbot-docs:latest
Modalità /resume      →  shellbot-create:latest
```

Questo perché i modelli specializzati hanno **system prompt ottimizzati** per il compito specifico:
- **Create/Fix**: comandi brevi e precisi, focus su creazione file
- **Docs/Reverse**: context window più ampia, focus su analisi e documentazione

Per i dettagli sui modelli specializzati, vedi [`modelfiles/README_MODELLI.md`](modelfiles/README_MODELLI.md).

## 📝 Formato Comandi JSON

Il LLM risponde **SOLO** con JSON (system prompt nel Modelfile):

```json
{
  "cmd1": "mkdir -p /path/proj",
  "cmd2": "cat << 'EOF' > /path/proj/readme.md\n# Progetto\nDescrizione...\nEOF",
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

Il `CommandParser` (`src/command_parser.py`, 866 righe) è un motore di **estrazione e riparazione JSON** estremamente robusto:

### Estrazione comandi (in ordine di priorità)

| Strategia | Descrizione |
|-----------|-------------|
| **1. Markdown code blocks** | ```json {...}``` - priorità massima |
| **2. Pattern `{"cmdN":`** | Cerca l'inizio dei comandi ovunque nel testo |
| **3. Response starts with `{`** | Se la risposta inizia con graffa |
| **4. Fallback regex** | Estrazione manuale per casi disperati |

### Fix automatici applicati

| Problema | Fix applicato |
|----------|---------------|
| **Stringhe non chiuse** | Chiude automaticamente prima del prossimo `cmdN` |
| **Newline non escapeati** | Converte `\n` reali in `\\n` dentro stringhe |
| **Tab non escapeati** | Converte `\t` reali in `\\t` |
| **Smart quotes / En-dashes / Em-dashes** | Converte punteggiatura tipografica in ASCII |
| **Double colons** | `"key":  :` → `"key":` |
| **Trailing commas** | Rimuove `,` prima di `}` o `]` |
| **JSON comments** | Rimuove `//` e `/* */` |
| **Malformed keys** | `"cmdtris"` → `"cmd1"`, `"cmdhtml:"` → `"cmd1"` |
| **EOF malformato** | Corregge `'EOF"` → `'EOF'` negli heredoc |
| **Escape PowerShell** | Fixa backtick, parentesi quadre, pipe |
| **Balanced brace extraction** | Estrae JSON troncato bilanciando le graffe |
| **Thinking tags** | Rimuove `<think>...</think>` |

### Formato comandi supportati

```json
// Formato multi-comando (attuale)
{"cmd1": "mkdir proj", "cmd2": "cat << 'EOF' > file\ncontent\nEOF"}

// Formato legacy (singolo)
{"command": "mkdir proj"}
```

## 🔧 Fix Automatico Post-Esecuzione

Dopo aver eseguito i comandi in modalità `/new` o `/fix`, il bridge **scansiona automaticamente** i file generati e applica fix per errori di sintassi comuni:

| Linguaggio | Fix applicati |
|------------|---------------|
| **Python** | sintassi `print()`, stringhe, parentesi, backslash |
| **Java** | punto e virgola, `System.out.println`, parentesi |
| **JavaScript** | escape characters, sintassi base |
| **Shell** | escape characters |

I fix vengono applicati **automaticamente** senza intervento dell'utente.

## 📖 Truncated Response Handling

Se la risposta del LLM viene **troncata a metà** (output troppo lungo), il bridge:
1. Rileva che il JSON non è stato chiuso correttamente
2. Identifica l'ultimo numero di comando completato
3. Chiede al modello di **continuare dal punto di interruzione**
4. Unisce i comandi ricevuti con quelli precedenti

Questo evita di perdere tutto il lavoro generado quando il modello supera il limite di token.

## 🔒 Sicurezza

- **Safety mode**: richiede conferma per comandi distruttivi (`rm`, `rmdir`, ecc.)
- **Pattern bloccati**: `rm -rf /`, `sudo rm`, `mkfs`, `dd if=`
- **Working directory**: limitabile in `config.json`
- **Allowed directories**: whitelist opzionale
- **Validazione heredoc**: controlla sintassi `cat << 'EOF'`
- **Intercept scrittura .md**: usa Python invece di shell per evitare problemi con apici e formattazione

## 📁 Struttura Progetto

```
my_claude_code/
├── main.py                          # Entry point CLI/GUI/TUI
├── requirements.txt                 # Dipendenze Python
├── Modelfile                        # Modelfile base (bash/POSIX, Qwen3-Coder)
├── README.md                        # Questo file
├── .ollama_bridge_state.json        # Stato persistente (modello, impostazioni)
│
├── modelfiles/
│   ├── README_MODELLI.md            # Documentazione modelli specializzati
│   ├── Modelfile_gemma4             # Gemma 4 base
│   ├── Modelfile_gemma4_create      # Gemma 4 per /new e /fix
│   ├── Modelfile_gemma4_docs        # Gemma 4 per /reverse
│   ├── Modelfile_windows            # Windows/PowerShell base
│   ├── Modelfile_windows_create     # Windows per /new e /fix
│   └── Modelfile_windows_docs       # Windows per /reverse
│
├── create_gemma4_modelfiles.py      # Utility per generare modelfile Gemma 4
├── bridge_test.py                   # Script di test semplificato
├── test_gemma4_parsing.py           # Test parsing Gemma 4
│
├── src/
│   ├── ollama_client.py             # Client Ollama API (streaming, auto-restart)
│   ├── file_operations.py           # Filesystem executor (shell detection)
│   ├── command_parser.py            # JSON extraction & repair engine (866 righe)
│   ├── session_manager.py           # Gestione sessioni e message history
│   ├── project_scanner.py           # Scansione progetti per /reverse
│   ├── system_prompt.py             # Placeholder (system prompt nei Modelfile)
│   ├── chat_ui.py                   # TUI (Textual framework)
│   └── gui.py                       # GUI (Tkinter, 1948 righe)
│
├── logs/
│   ├── ollama_*.log                 # Log esecuzioni
│   └── requests/                    # Request/response JSON completi
│
├── sessions/                        # Sessioni salvate (JSON)
└── examples/
    └── fix_best_practices.md        # Best practices per modalità /fix
```

## 📊 Log e Debug

Tutte le esecuzioni vengono loggate in:

- `logs/ollama_*.log` - Log generali
- `logs/requests/*.json` - Request/response JSON completi

Per visualizzare l'ultimo log:
```bash
# PowerShell
Get-Content logs/ollama_*.log -Tail 50 -Wait

# Bash
tail -f logs/ollama_*.log
```

## ✅ Task Tracking

### Completati

| ID | Task | Stato |
|----|------|-------|
| 1 | Project Structure | ✅ |
| 2 | Ollama Client | ✅ |
| 3 | System Prompt (nei Modelfile) | ✅ |
| 4 | Command Parser (866 righe, esteso) | ✅ |
| 5 | Session Manager | ✅ |
| 6 | CLI Interface | ✅ |
| 7 | Configuration (hardcoded defaults) | ✅ |
| 8 | Examples | ✅ |
| 9 | UI (TUI + GUI) | ✅ |
| 10 | Modello a runtime | ✅ |
| 11 | **Modalità /fix** | ✅ |
| 12 | **Modalità /new** | ✅ |
| 13 | **Modalità /reverse** | ✅ |
| 14 | **Modalità /resume** | ✅ |
| 15 | **Fix automatico sintassi** | ✅ |
| 16 | **readme.md come unico file** | ✅ |
| 17 | **Model switching automatico** | ✅ |
| 18 | **Truncated response handling** | ✅ |
| 19 | **Modelli specializzati** | ✅ |
| 20 | **Shell auto-detection** | ✅ |

### Futuri

| ID | Task |
|----|------|
| 21 | Multi-file batch operations |
| 22 | Web interface |
| 23 | Async support |
| 24 | Tool calling nativo (se supportato) |

## ⚙️ Modelfile Ollama

Il system prompt è nel **Modelfile** di Ollama, non nel codice Python.

### Modelfile Base (`Modelfile`)
- **Base model**: Qwen3-Coder-15B
- **Context**: 8192 token
- **Specializzazione**: bash/POSIX heredoc syntax
- **Istruzioni**: `/new`, `/fix`, `/reverse`, `/resume`

### Modelli Specializzati (`modelfiles/`)
- **`*_create`**: ottimizzati per creazione/modifica file (comandi brevi)
- **`*_docs`**: ottimizzati per analisi codice e documentazione (context ampio)
- **Varianti**: Windows/PowerShell e Gemma 4

Per creare un modello custom:
```bash
ollama create shellbot -f Modelfile
```

Per rigenerare tutti i modelli shellbot:
```bash
python main.py --rebuild-shellbot
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
