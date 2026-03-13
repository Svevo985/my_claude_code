"""
System prompt per Ollama File System Bridge.

NOTA: Il system prompt principale è nel modelfile di Ollama.
Questo file contiene solo placeholder per compatibilità col codice esistente.

Il modelfile di Ollama già istruisce l'LLM a:
- Rispondere SOLO con JSON
- Usare cmd1, cmd2, cmd3... per i comandi
- Creare claude.md per tracciamento progetto
- Usare cat << 'EOF' > per creare file
- NON creare README.md separato (usa solo claude.md)

Se devi modificare il comportamento, aggiorna il modelfile con:
    ollama cp qwen2.5-codershellBot:latest qwen2.5-codershellBot-fix
    # Modifica il Modelfile
    ollama create qwen2.5-codershellBot-fix -f Modelfile
"""

# Placeholder vuoti - il system prompt è in Ollama
SYSTEM_PROMPT = ""
SYSTEM_PROMPT_COMPACT = ""
SYSTEM_PROMPT_NEW_PROJECT = ""
SYSTEM_PROMPT_REVERSE = ""
