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
    # Pattern per JSON dentro code block markdown
    JSON_BLOCK_PATTERN = re.compile(r'```(?:json)?\s*\n?({[^}]*})\s*\n?```', re.DOTALL | re.IGNORECASE)
    # Pattern per JSON nudo
    JSON_PATTERN = re.compile(r'\{[^{}]*\}', re.DOTALL)

    def parse(self, response: str) -> ParsedCommand:
        response = response.strip()

        # Prima cerca JSON dentro code block markdown
        block_matches = self.JSON_BLOCK_PATTERN.findall(response)
        if block_matches:
            return self._try_parse_json(block_matches[0], response)

        # Poi cerca JSON diretto
        if response.startswith('{') and response.endswith('}'):
            return self._try_parse_json(response, response)

        # Cerca JSON nel testo
        matches = self.JSON_PATTERN.findall(response)
        if matches:
            return self._try_parse_json(matches[0], response)

        return ParsedCommand(
            commands=[],
            raw_response=response,
            is_valid=False,
            error="Nessun comando JSON trovato"
        )

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
