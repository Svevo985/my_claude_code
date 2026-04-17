# Modello Operativo Attuale

Modello attivo per pipeline `/new` e `/fix`:

- Base: `qwen2.5-coder:7b`
- Alias bridge: `qwen2.5-coder-shellbot-create:latest`
- Modelfile: `modelfiles/Modelfile_qwen25_shellbot_create`

## Comandi

```powershell
# Pull base model
ollama pull qwen2.5-coder:7b

# Crea alias specializzato bridge
ollama create qwen2.5-coder-shellbot-create:latest -f modelfiles/Modelfile_qwen25_shellbot_create

# Verifica
ollama list
```

## Note

- Questo repository usa un solo modelfile operativo per evitare confusione.
- Il system prompt nel modelfile forza output JSON deterministico per la pipeline step-by-step.
