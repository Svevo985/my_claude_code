"""
Project Memory - Memoria di progetto per mantenere coerenza tra step.

Salva le decisioni architetturali (nomi file, ID, classi, funzioni)
e le rende disponibili ad ogni step successivo.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class ProjectMemory:
    """Memoria di progetto per tracciare decisioni architetturali."""
    
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.memory_file = project_path / ".project_memory.json"
        self.data = self._load()
    
    def _load(self) -> dict:
        """Carica la memoria esistente."""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "project_name": "",
            "description": "",
            "files": {},
            "contracts": {},
            "decisions": [],
            "created_at": datetime.now().isoformat()
        }
    
    def save(self):
        """Salva la memoria su file."""
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def set_project_info(self, name: str, description: str):
        """Imposta info generali del progetto."""
        self.data["project_name"] = name
        self.data["description"] = description
        self.save()
    
    def register_file(self, filename: str, purpose: str, elements: dict = None):
        """
        Registra un file nel contratto di progetto.
        
        elements: {
            "ids": ["id1", "id2"],
            "classes": ["class1", "class2"],
            "functions": ["func1", "func2"],
            "variables": ["var1", "var2"]
        }
        """
        if filename not in self.data["files"]:
            self.data["files"][filename] = {
                "purpose": purpose,
                "elements": elements or {},
                "created_at": datetime.now().isoformat()
            }
        else:
            # Aggiorna elementi se già esiste
            if elements:
                for key, values in elements.items():
                    if key not in self.data["files"][filename]["elements"]:
                        self.data["files"][filename]["elements"][key] = []
                    self.data["files"][filename]["elements"][key].extend(values)
                    # Rimuovi duplicati
                    self.data["files"][filename]["elements"][key] = list(set(
                        self.data["files"][filename]["elements"][key]
                    ))
        self.save()
    
    def get_file_contract(self, filename: str) -> Optional[dict]:
        """Ottieni il contratto di un file (elementi esposti)."""
        return self.data["files"].get(filename)
    
    def get_all_contracts(self) -> dict:
        """Ottieni tutti i contratti dei file."""
        return self.data["files"]
    
    def add_decision(self, decision: str):
        """Aggiunge una decisione architetturale."""
        self.data["decisions"].append({
            "decision": decision,
            "timestamp": datetime.now().isoformat()
        })
        self.save()
    
    def get_memory_summary(self) -> str:
        """
        Genera un riepilogo della memoria da iniettare nel prompt.
        Questo aiuta l'LLM a ricordare le decisioni prese.
        """
        if not self.data["files"]:
            return "Nessuna memoria di progetto ancora."
        
        summary = "## CONTRATTO DI PROGETTO (Decisioni prese finora)\n\n"
        summary += f"**Progetto**: {self.data.get('project_name', 'N/A')}\n"
        summary += f"**Descrizione**: {self.data.get('description', 'N/A')[:100]}...\n\n"
        
        summary += "### File registrati:\n"
        for filename, info in self.data["files"].items():
            summary += f"\n**{filename}** - {info['purpose']}\n"
            elements = info.get("elements", {})
            
            # Mostra elementi normali
            if elements.get("ids"):
                summary += f"  - ID esposti: {', '.join(elements['ids'])}\n"
            if elements.get("classes"):
                summary += f"  - Classi: {', '.join(elements['classes'])}\n"
            if elements.get("functions"):
                summary += f"  - Funzioni: {', '.join(elements['functions'])}\n"
            if elements.get("variables"):
                summary += f"  - Variabili: {', '.join(elements['variables'][:5])}...\n"
            if elements.get("selectors"):
                summary += f"  - Selettori CSS: {', '.join(elements['selectors'][:5])}...\n"
            if elements.get("used_ids"):
                summary += f"  - ID usati nel JS: {', '.join(elements['used_ids'])}\n"
            if elements.get("used_classes"):
                summary += f"  - Classi usate nel JS: {', '.join(elements['used_classes'])}\n"
            
            # Mostra validazioni
            if elements.get("has_css_link"):
                has_link = elements["has_css_link"][0] == "True"
                summary += f"  - {'✅' if has_link else '❌'} Link a style.css: {has_link}\n"
            if elements.get("has_js_link"):
                has_link = elements["has_js_link"][0] == "True"
                summary += f"  - {'✅' if has_link else '❌'} Link a script.js: {has_link}\n"
            if elements.get("has_inline_style"):
                has_inline = elements["has_inline_style"][0] == "True"
                if has_inline:
                    summary += f"  - ⚠️ CSS INLINE rilevato (VIOLAZIONE!)\n"
            if elements.get("has_inline_script"):
                has_inline = elements["has_inline_script"][0] == "True"
                if has_inline:
                    summary += f"  - ⚠️ JS INLINE rilevato (VIOLAZIONE!)\n"
        
        if self.data.get("decisions"):
            summary += "\n### Decisioni/Note:\n"
            for d in self.data["decisions"][-5:]:
                summary += f"- {d['decision']}\n"
        
        return summary
    
    def clear(self):
        """Resetta la memoria."""
        self.data = {
            "project_name": "",
            "description": "",
            "files": {},
            "contracts": {},
            "decisions": [],
            "created_at": datetime.now().isoformat()
        }
        self.save()
