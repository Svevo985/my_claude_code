# Modelli ShellBot Specializzati

## Strategia: 2 Modelli Separati

Dato che `phi4-mini` (2.5GB) è un modello piccolo, ha difficoltà a seguire istruzioni complesse e multiple. La soluzione è **separare i compiti** in due modelli specializzati.

---

## 📦 Modelli Creati

### 1. `phi4-mini-shellbot-create:latest`
**Specializzazione:** Creazione e modifica file (`/new`, `/fix`)

**Configurazione:**
- `num_ctx`: 8192
- `num_predict`: 2048
- Focus: Comandi PowerShell brevi e precisi

**System Prompt:**
- Istruzioni semplificate per creare/fixare file
- Esempi chiari di JSON con 1-2 comandi
- Regole: NO markdown, NO spiegazioni, solo JSON

**Esempio output:**
```json
{"cmd1": "Set-Content -Path 'main.py' -Value 'print(\"hello\")'"}
```

---

### 2. `phi4-mini-shellbot-docs:latest`
**Specializzazione:** Documentazione reverse engineering (`/reverse`)

**Configurazione:**
- `num_ctx`: 16384 (più contesto per analisi codice)
- `num_predict`: 4096 (più spazio per documentazione lunga)
- Focus: Analisi codice Java + generazione documentazione

**System Prompt:**
- Istruzioni focalizzate su documentazione
- Esempio di UN comando con tutto il contenuto
- Regole Java: concentrati su *Service.java per business logic

**Esempio output:**
```json
{"cmd1": "Set-Content -Path 'DOCUMENTAZIONE.md' -Value '# Title\n\n## Section\nContent...'"}
```

---

## 🔄 Switch Automatico

Il codice **cambia automaticamente** modello in base alla modalità:

```python
# CLI (main.py)
def set_mode(self, m: str):
    if m in ('fix', 'new'):
        self.ollama.model = self.model_create
    elif m == 'reverse':
        self.ollama.model = self.model_docs

# GUI (gui.py)
# Stessa logica nei comandi /fix, /new, /reverse
```

---

## 📊 Vantaggi

| Singolo Modello | 2 Modelli Specializzati |
|----------------|------------------------|
| ❌ Prompt confusionario | ✅ Prompt focalizzato |
| ❌ Esempi lunghi confondono | ✅ Esempi semplici e chiari |
| ❌ LLM impazzisce | ✅ LLM sa esattamente cosa fare |
| ❌ Output inconsistente | ✅ Output coerente e prevedibile |
| ❌ 8 anni per rispondere | ✅ Più veloce e efficiente |

---

## 🚀 Utilizzo

### CLI
```bash
python main.py
# Il modello cambia automaticamente in base al comando

/fix /path/progetto "aggiungi validazione"
# → Usa phi4-mini-shellbot-create:latest

/reverse /path/progetto
# → Usa phi4-mini-shellbot-docs:latest
```

### GUI
```bash
python src/gui.py
# Clicca sui bottoni o usa i comandi
# Il modello cambia automaticamente
```

---

## 🛠️ Ricreare i Modelli

Se devi ricrearli:

```bash
# Modello CREATE/FIX
ollama create phi4-mini-shellbot-create:latest -f modelfiles/Modelfile_windows_create

# Modello DOCS/REVERSE
ollama create phi4-mini-shellbot-docs:latest -f modelfiles/Modelfile_windows_docs
```

---

## 📝 Note

- **Non usare `num_predict: -1`**: Il modello potrebbe generare all'infinito
- **Mantenere prompt brevi**: phi4-mini si confonde con troppe istruzioni
- **Esempi chiari**: Mostrare ESATTAMENTE il formato desiderato
- **Una specializzazione per modello**: Non mescolare compiti diversi

---

## 🔮 Futuro

Se phi4-mini è comunque troppo lento/debole:

1. **Upgrade a phi4:latest** (4.7GB) - molto più capace
2. **Upgrade a llama3.2:latest** (3GB) - ottimo per istruzioni
3. **Upgrade a qwen2.5-coder:3b** (3GB) - specializzato codice

```bash
ollama pull phi4:latest
# Poi ricrea i modelli con FROM phi4:latest
```
