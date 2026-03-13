# Esempi di Utilizzo

## Esempio 1: Creare un Nuovo Progetto

```
👤 Tu: Crea un nuovo progetto Python con Flask

🤖 LLM sta pensando...
  Comando: mkdir -p flask_project
  Output: ✓ Comando eseguito

🤖 LLM sta pensando...
  Comando: echo 'from flask import Flask\n\napp = Flask(__name__)\n\n@app.route("/")\ndef hello():\n    return "Hello World"\n\nif __name__ == "__main__":\n    app.run(debug=True)' > flask_project/app.py
  Output: ✓ File scritto: flask_project/app.py

🤖 LLM sta pensando...
  Comando: echo 'Flask>=2.0.0' > flask_project/requirements.txt
  Output: ✓ File scritto: flask_project/requirements.txt
```

## Esempio 2: Analisi di un Progetto Esistente

```
👤 Tu: Analizza la struttura di questo progetto

🤖 LLM sta pensando...
  Comando: find . -type f -name "*.py" | head -20
  Output: ✓ ./main.py
           ./src/__init__.py
           ./src/ollama_client.py
           ./src/file_operations.py

🤖 LLM sta pensando...
  Comando: cat main.py
  Output: ✓ #!/usr/bin/env python3 ...
  
  (Contenuto letto automaticamente e dato in pasto all'LLM)

🤖 LLM sta pensando...
  Questo progetto è un bridge tra Ollama e il file system. 
  La struttura è ben organizzata con moduli separati per:
  - ollama_client.py: comunicazione API
  - file_operations.py: operazioni file system
  - command_parser.py: parsing JSON
  ...
```

## Esempio 3: Code Review

```
👤 Tu: Fai code review del file src/ollama_client.py

🤖 LLM sta pensando...
  Comando: cat src/ollama_client.py
  Output: ✓ (contenuto del file)

🤖 LLM sta pensando...
  ## Code Review

  **Punti di forza:**
  1. Buona separazione delle responsabilità
  2. Gestione corretta degli errori
  3. Supporto streaming implementato

  **Suggerimenti:**
  1. Aggiungere retry logic per le chiamate API
  2. Implementare timeout configurabile per richiesta
  3. Aggiungere logging per debug
```

## Esempio 4: Ottimizzazione Codice

```
👤 Tu: Ottimizza la funzione execute_command in file_operations.py

🤖 LLM sta pensando...
  Comando: cat src/file_operations.py
  Output: ✓ (contenuto del file)

🤖 LLM sta pensando...
  Comando: echo '...codice ottimizzato...' > src/file_operations.py
  Output: ✓ File scritto: src/file_operations.py
  
  **Ottimizzazioni applicate:**
  1. Ridotta allocazione memoria
  2. Migliorata gestione errori
  3. Aggiunto caching per operazioni ripetute
```

## Comandi Shell Supportati

| Comando | Descrizione | Esempio JSON |
|---------|-------------|--------------|
| `cat` | Legge file | `{"command": "cat file.txt"}` |
| `echo >` | Scrive file | `{"command": "echo 'ciao' > file.txt"}` |
| `echo >>` | Aggiunge a file | `{"command": "echo 'ciao' >> file.txt"}` |
| `mkdir` | Crea directory | `{"command": "mkdir -p new/dir"}` |
| `ls` | Lista file | `{"command": "ls -la"}` |
| `find` | Cerca file | `{"command": "find . -name '*.py'"}` |
| `grep` | Cerca testo | `{"command": "grep -r 'pattern' ."`} |
| `cp` | Copia file | `{"command": "cp src dest"}` |
| `mv` | Sposta file | `{"command": "mv old new"}` |
| `rm` | Rimuove file | `{"command": "rm file.txt"}` |

## Best Practices

1. **Leggi prima di scrivere**: Sempre leggere un file prima di modificarlo
2. **Comandi atomici**: Un comando per volta per tracciabilità
3. **Verifica dopo scrittura**: Leggere il file dopo averlo scritto per conferma
4. **Usa percorsi relativi**: Per portabilità del progetto
