"""Parser per estrarre comandi JSON dalle risposte LLM."""

import json
import re
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ParsedCommand:
    commands: List[str]
    raw_response: str
    is_valid: bool
    error: Optional[str] = None

class CommandParser:
    # Pattern per JSON dentro code block markdown - PRIORITA' MASSIMA
    JSON_BLOCK_PATTERN = re.compile(r'```(?:json)?\s*\n?({.+?})\s*\n?```', re.DOTALL | re.IGNORECASE)
    # Pattern per trovare inizio comandi nel testo - cerca "cmdN":
    CMD_START_PATTERN = re.compile(r'\{["\s]*cmd\d+["\s]*:', re.DOTALL)

    def parse(self, response: str) -> ParsedCommand:
        original_response = response
        response = response.strip()

        # 0. RIMUOVI thinking tags (<think>...</think>) - alcuni modelli li usano
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)

        # 0b. RIMUOVI fence markdown di apertura (```json o ```)
        response = re.sub(r'^```(?:json)?\s*\n?', '', response, flags=re.IGNORECASE).strip()

        # 1. PRIORITA': cerca JSON dentro code block markdown (con chiusura ```)
        block_matches = self.JSON_BLOCK_PATTERN.findall(response)
        if block_matches:
            return self._try_parse_json(block_matches[0], response)

        # 2. Cerca pattern {"cmdN": nel testo - PUO' ESSERE DOVUNQUE
        cmd_match = self.CMD_START_PATTERN.search(response)
        if cmd_match:
            start_pos = cmd_match.start()
            potential_json = response[start_pos:]
            json_str = self._extract_balanced_json(potential_json)
            if json_str:
                return self._try_parse_json(json_str, original_response)
            return self._try_parse_json(potential_json, original_response)

        # 3. Se la response INIZIA con { (anche senza cmd), prova a estrarre
        if response.startswith('{'):
            json_str = self._extract_balanced_json(response)
            if json_str:
                return self._try_parse_json(json_str, original_response)
            return self._try_parse_json(response, original_response)

        return ParsedCommand(
            commands=[],
            raw_response=original_response,
            is_valid=False,
            error="Nessun comando JSON trovato"
    )

    def _extract_balanced_json(self, text: str) -> str:
        """Estrae JSON bilanciato contando parentesi graffe."""
        if not text or not text.startswith('{'):
            return ""
        
        depth = 0
        in_string = False
        escape_next = False
        in_heredoc = False
        heredoc_marker = None
        
        i = 0
        while i < len(text):
            char = text[i]
            
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if char == '\\' and in_string:
                escape_next = True
                i += 1
                continue
            
            if char == '"' and not escape_next:
                # Controlla se siamo in un heredoc
                if not in_string and i + 1 < len(text) and text[i:i+3] == "'EO":
                    # Inizio heredoc: 'EOF' o simile
                    in_heredoc = True
                    # Trova la fine del marker
                    end_marker = text.find("'", i + 1)
                    if end_marker != -1:
                        heredoc_marker = text[i:end_marker + 1]
                        i = end_marker + 1
                        continue
                
                if in_heredoc and heredoc_marker:
                    # Cerca la fine dell'heredoc
                    eof_pos = text.find("\nEOF", i)
                    if eof_pos != -1:
                        # Trova la chiusura del heredoc
                        after_eof = text.find("'", eof_pos + 4)
                        if after_eof != -1:
                            i = after_eof + 1
                            in_heredoc = False
                            heredoc_marker = None
                            continue
                
                in_string = not in_string
                i += 1
                continue
            
            if not in_string and not in_heredoc:
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        return text[:i+1]
            
            i += 1
        
        # Se non trova chiusura, ritorna quello che c'è (JSON troncato)
        # Il parser proverà a fixarlo
        return text if text.startswith('{') else ""

    def _try_parse_json(self, json_str: str, raw_response: str) -> ParsedCommand:
        try:
            data = json.loads(json_str)
            if not isinstance(data, dict):
                return ParsedCommand([], raw_response, False, "JSON non è un oggetto")

            commands = []

            # Formato 1: {"command": "..."} (vecchio formato)
            if "command" in data:
                if isinstance(data["command"], str):
                    commands.append(self._clean_command(data["command"]))
                return ParsedCommand(commands, raw_response, True)

            # Formato 2: {"cmd1": "...", "cmd2": "...", ...} (nuovo formato shellbot)
            cmd_keys = sorted([k for k in data.keys() if k.startswith("cmd")])
            for key in cmd_keys:
                if isinstance(data[key], str):
                    commands.append(self._clean_command(data[key]))

            if commands:
                return ParsedCommand(commands, raw_response, True)

            return ParsedCommand([], raw_response, False, "Nessun comando trovato nel JSON")

        except json.JSONDecodeError as e:
            # Prova a fixare JSON con newline non escapeati
            fixed_json = self._fix_newline_in_string_json(json_str)
            if fixed_json != json_str:
                try:
                    data = json.loads(fixed_json)
                    if isinstance(data, dict):
                        commands = []
                        cmd_keys = sorted([k for k in data.keys() if k.startswith("cmd")])
                        for key in cmd_keys:
                            if isinstance(data[key], str):
                                commands.append(self._clean_command(data[key]))
                        if commands:
                            return ParsedCommand(commands, raw_response, True)
                except:
                    pass

            # Ultimo tentativo: estrazione manuale con regex
            manual_commands = self._extract_commands_manually(raw_response)
            if manual_commands:
                # Pulisci i comandi estratti manualmente
                manual_commands = [self._clean_command(cmd) for cmd in manual_commands]
                return ParsedCommand(manual_commands, raw_response, True)

            return ParsedCommand([], raw_response, False, f"JSON non valido: {e}")
    
    def _clean_command(self, cmd: str) -> str:
        """
        Pulisce il comando da caratteri di escape e quote di troppo.
        """
        # Rimuovi " finale se presente (errore comune di parsing)
        if cmd.endswith('"') and not cmd.endswith('\\"'):
            cmd = cmd[:-1]

        # Rimuovi " iniziale se presente
        if cmd.startswith('"'):
            cmd = cmd[1:]

        # Fixa escape sequence doppi PRIMA di rimuovere EOF
        # Questo converte \\\\n in \\n, così la regex EOF può matchare
        cmd = cmd.replace('\\\\n', '\\n')
        cmd = cmd.replace('\\\\t', '\\t')
        cmd = cmd.replace('\\\\\'', '\\\'')
        cmd = cmd.replace('\\"', '"')

        # ✅ FIX: Correggi 'EOF" → 'EOF' (errore comune LLM)
        cmd = cmd.replace("'EOF\"", "'EOF'")
        cmd = cmd.replace("'EOF\" ", "'EOF' ")
        
        # ✅ FIX: Correggi EOF" → EOF (virgoletta extra a fine)
        cmd = re.sub(r'EOF"\s*$', 'EOF', cmd)
        cmd = re.sub(r'EOF" ', 'EOF ', cmd)

        # Rimuovi EOF finale dagli heredoc shell (errore comune di parsing)
        # Pattern: newline (reale o escapeata) seguita da EOF" o EOF solo a fine stringa
        cmd = re.sub(r'\n\s*EOF\s*$', '', cmd)
        cmd = re.sub(r'\n\s*EOF"\s*$', '', cmd)
        # Anche per \\n letterali (dopo il fix sopra diventano \n reali nella stringa)
        cmd = re.sub(r'\\n\s*EOF\s*$', '', cmd)
        cmd = re.sub(r'\\n\s*EOF"\s*$', '', cmd)

        # Rimuovi spazi extra a inizio/fine
        cmd = cmd.strip()

        return cmd
    
    def _fix_json_escapes(self, json_str: str) -> str:
        """
        Fixa JSON con newline e tab non escapeati correttamente.
        Converte \n reali in \\n per le stringhe JSON.
        Gestisce anche backslash multipli malformati.
        """
        result = []
        in_string = False
        escape_next = False
        i = 0

        while i < len(json_str):
            char = json_str[i]

            if escape_next:
                result.append(char)
                # Se dopo backslash c'è un altro backslash, controlla il carattere successivo
                if char == '\\':
                    # Guarda avanti per vedere se è seguito da newline
                    if i + 1 < len(json_str) and json_str[i + 1] == '\n':
                        # \\ seguito da \n reale - mantieni \\ e converti \n
                        result.append('\\n')
                        i += 1
                escape_next = False
                i += 1
                continue

            if char == '\\':
                result.append(char)
                escape_next = True
                i += 1
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if in_string and char == '\n':
                # Newline dentro stringa - escapealo
                result.append('\\n')
                i += 1
                continue

            if in_string and char == '\t':
                # Tab dentro stringa - escapealo
                result.append('\\t')
                i += 1
                continue

            result.append(char)
            i += 1

        return ''.join(result)

    def _fix_newline_in_string_json(self, json_str: str) -> str:
        """
        Fixa JSON dove le newline reali rompono il parsing.
        Questo gestisce il caso comune dove l'LLM mette \n letterali
        invece di \\n nelle stringhe JSON.
        """
        # Prima prova: se il JSON parse già, returnalo
        try:
            json.loads(json_str)
            return json_str
        except:
            pass

        # Secondo: usa _fix_json_escapes
        fixed = self._fix_json_escapes(json_str)
        try:
            json.loads(fixed)
            return fixed
        except:
            pass

        # Terzo: estrai solo i comandi con regex manuale
        # Pattern: "cmdN": "contenuto"
        import re
        commands = {}
        
        # Estrai il blocco JSON se dentro markdown
        block_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if block_match:
            json_str = block_match.group(0)
        
        # Trova tutti i cmdN
        cmd_pattern = r'"(cmd\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"'
        for match in re.finditer(cmd_pattern, json_str, re.DOTALL):
            key = match.group(1)
            value = match.group(2)
            # Unescape il valore
            value = value.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
            commands[key] = value
        
        if commands:
            # Ricostruisci JSON valido
            return json.dumps(commands, ensure_ascii=False)
        
        return json_str
    
    def _extract_commands_manually(self, response: str) -> List[str]:
        """
        Estrae comandi manualmente quando il JSON è troppo malformato.
        Cerca pattern come "cmd1": "..." nel testo.
        """
        import re
        commands = []
        
        # Prima estrai il code block JSON se presente
        block_match = re.search(r'```(?:json)?\s*\n?({.*?})\s*\n?```', response, re.DOTALL)
        if block_match:
            response = block_match.group(1)
        
        # Pattern per estrarre "cmdN": "..." gestendo stringhe multilinea
        # Questo pattern cattura tutto tra "cmdN": " e il prossimo " non escapeato
        pattern = r'"(cmd\d+)"\s*:\s*"((?:(?<!\\)(?:\\\\)*"|[^"])*?)"'
        
        # Approccio alternativo: cerca "cmdN": e poi cattura fino alla prossima chiave o fine
        lines = response.split('\n')
        current_cmd = None
        current_value = []
        
        for line in lines:
            # Cerca inizio di un comando
            cmd_match = re.match(r'\s*"(cmd\d+)"\s*:\s*"(.*)$', line)
            if cmd_match:
                # Se c'era un comando precedente, salvalo
                if current_cmd and current_value:
                    cmd_str = '\n'.join(current_value)
                    # Rimuovi " finale se presente
                    if cmd_str.endswith('"'):
                        cmd_str = cmd_str[:-1]
                    # Unescape
                    cmd_str = cmd_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                    commands.append(cmd_str)
                
                current_cmd = cmd_match.group(1)
                current_value = [cmd_match.group(2)]
            elif current_cmd:
                # Continua il comando precedente
                current_value.append(line)
        
        # Salva l'ultimo comando
        if current_cmd and current_value:
            cmd_str = '\n'.join(current_value)
            if cmd_str.rstrip().endswith('"'):
                cmd_str = cmd_str.rstrip()[:-1]
            # Fixa escape sequence
            cmd_str = cmd_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
            # Rimuovi EOF finale dagli heredoc shell
            cmd_str = re.sub(r'\n\s*EOF\s*$', '', cmd_str)
            cmd_str = re.sub(r'\n\s*EOF"\s*$', '', cmd_str)
            commands.append(cmd_str)

        return commands
    
    def validate_command_safety(self, command: str) -> tuple[bool, str]:
        dangerous = [
            ('rm -rf /', "Rimozione root"),
            ('sudo rm', "Rimozione con sudo"),
            ('mkfs', "Formattazione"),
            ('dd if=', "Scrittura dispositivo"),
        ]
        cmd_lower = command.lower()
        for pattern, desc in dangerous:
            if pattern.lower() in cmd_lower:
                return (False, f"Comando bloccato: {desc}")
        return (True, "OK")
