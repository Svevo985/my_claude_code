"""Parser per estrarre comandi JSON dalle risposte LLM."""

import json
import re
from dataclasses import dataclass
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

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
    # Pattern放宽ato per chiavi simili a comandi (es. cmdtris, cmdhtml, cmdcss, cm2, new1)
    LOOSE_CMD_START_PATTERN = re.compile(r'\{["\s]*[A-Za-z_]*cmd[A-Za-z_]*["\s]*:', re.DOTALL | re.IGNORECASE)

    def parse(self, response: str) -> ParsedCommand:
        logger.debug(f"CommandParser.parse called with response length {len(response)}")
        original_response = response
        response = response.strip()

        # 0. RIMUOVI thinking tags (<think>...</think>) - alcuni modelli li usano
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)

        # 0b. RIMUOVI fence markdown di apertura (```json o ```)
        response = re.sub(r'^```(?:json)?\s*\n?', '', response, flags=re.IGNORECASE).strip()

        # 1. PRIORITA': cerca JSON dentro code block markdown (con chiusura ```)
        block_matches = self.JSON_BLOCK_PATTERN.findall(response)
        if block_matches:
            logger.debug(f"CommandParser matched JSON_BLOCK_PATTERN, found block of length {len(block_matches[0])}")
            return self._try_parse_json(block_matches[0], response)

        # 2. Cerca pattern {"cmdN": nel testo - PUO' ESSERE DOVUNQUE
        cmd_match = self.CMD_START_PATTERN.search(response)
        if cmd_match:
            start_pos = cmd_match.start()
            logger.debug(f"CommandParser matched CMD_START_PATTERN at position {start_pos}")
            potential_json = response[start_pos:]
            json_str = self._extract_balanced_json(potential_json)
            if json_str:
                return self._try_parse_json(json_str, original_response)
            return self._try_parse_json(potential_json, original_response)

        # 3. Se la response INIZIA con { (anche senza cmd), prova a estrarre
        if response.startswith('{'):
            logger.debug("CommandParser response starts with '{'")
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

    def _fix_unclosed_strings_json(self, json_str: str) -> str:
        """
        Fixa JSON dove le stringhe non sono chiuse correttamente.
        Quando trova "cmdN": dopo una stringa non chiusa, chiude automaticamente la precedente.
        """
        result = []
        in_string = False
        escape_next = False
        i = 0
        
        while i < len(json_str):
            char = json_str[i]
            
            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue
            
            if char == '\\' and in_string:
                result.append(char)
                escape_next = True
                i += 1
                continue
            
            # Controlla se stiamo per iniziare un nuovo cmd mentre siamo in una stringa
            if in_string and char == '"':
                # Guarda avanti per vedere se questa virgoletta chiude la stringa
                # e subito dopo c'è una virgola e un nuovo cmd
                rest = json_str[i+1:].lstrip()
                if rest.startswith(',') or rest.startswith('}'):
                    # Questa virgoletta chiude la stringa correttamente
                    result.append(char)
                    in_string = False
                    i += 1
                    continue
                elif re.match(r'"cmd\d+"', rest):
                    # Nuova chiave cmd - chiudi la stringa corrente se non lo è già
                    result.append(char)
                    in_string = False
                    i += 1
                    continue
                else:
                    # Virgoletta nel mezzo della stringa - potrebbe essere parte del contenuto
                    result.append(char)
                    i += 1
                    continue
            
            # FIX CRITICO: se troviamo "cmdN": mentre siamo in una stringa, chiudila forzatamente
            if in_string:
                # Cerca se nei prossimi caratteri c'è un nuovo cmd
                lookahead = json_str[i:i+20]
                cmd_match = re.match(r'[^"]*"\s*,\s*"cmd\d+"', lookahead)
                if cmd_match:
                    # Chiudi forzatamente la stringa corrente
                    result.append('",')
                    in_string = False
                    # Salta fino alla prossima chiave cmd
                    skip_to = json_str.find('"cmd', i)
                    if skip_to != -1:
                        i = skip_to
                        continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                result.append(char)
                i += 1
                continue
            
            result.append(char)
            i += 1
        
        # Se siamo ancora in una stringa alla fine, chiudila
        if in_string:
            result.append('"')
        
        return ''.join(result)
    
    def _fix_powershell_string_escapes(self, json_str: str) -> str:
        """
        Fixa problemi specifici di PowerShell nelle stringhe JSON:
        - Caratteri speciali PowerShell non escapeati
        - Backtick che rompono il parsing
        - Parentesi e pipe nel contenuto
        """
        # Pattern per trovare i valori delle stringhe JSON
        def fix_string_value(match):
            key = match.group(1)
            value = match.group(2)
            
            # Escape backtick per PowerShell
            value = value.replace('`', '``')
            
            # Escape parentesi quadre nel contenuto (rompono PowerShell)
            # Ma non quelle già escapeate
            value = re.sub(r'(?<!\\)\[', r'\[', value)
            value = re.sub(r'(?<!\\)\]', r'\]', value)
            
            # Escape pipe nel contenuto
            value = re.sub(r'(?<!\\)\|', r'\|', value)
            
            return f'"{key}": "{value}"'
        
        # Applica solo ai valori cmd
        pattern = r'"(cmd\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"'
        return re.sub(pattern, fix_string_value, json_str, flags=re.DOTALL)

    def _strip_json_comments(self, text: str) -> str:
        """Rimuove commenti // e /* */ da JSON-like, rispettando le stringhe."""
        if not text:
            return text

        result = []
        in_string = False
        escape_next = False
        i = 0

        while i < len(text):
            char = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""

            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue

            if char == '\\' and in_string:
                result.append(char)
                escape_next = True
                i += 1
                continue

            if char == '"':
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if not in_string and char == '/' and nxt == '/':
                i += 2
                while i < len(text) and text[i] not in '\r\n':
                    i += 1
                continue

            if not in_string and char == '/' and nxt == '*':
                i += 2
                while i + 1 < len(text) and not (text[i] == '*' and text[i + 1] == '/'):
                    i += 1
                if i + 1 < len(text):
                    i += 2
                continue

            result.append(char)
            i += 1

        return ''.join(result)

    def _strip_trailing_commas(self, text: str) -> str:
        """Rimuove trailing comma prima di } o ] fuori dalle stringhe."""
        if not text:
            return text

        result = []
        in_string = False
        escape_next = False
        i = 0

        while i < len(text):
            char = text[i]

            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue

            if char == '\\' and in_string:
                result.append(char)
                escape_next = True
                i += 1
                continue

            if char == '"':
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if not in_string and char == ',':
                j = i + 1
                while j < len(text) and text[j].isspace():
                    j += 1
                if j < len(text) and text[j] in '}]':
                    i += 1
                    continue

            result.append(char)
            i += 1

        return ''.join(result)

    def _normalize_json_candidate(self, json_str: str) -> str:
        """Normalizza output JSON-like (fence/commenti/testo extra)."""
        candidate = (json_str or "").strip()
        if not candidate:
            return ""

        # Normalizza punteggiatura tipografica prodotta da alcuni modelli
        candidate = (
            candidate
            .replace('\u201c', '"')
            .replace('\u201d', '"')
            .replace('\u201e', '"')
            .replace('\u201f', '"')
            .replace('\u2019', "'")
            .replace('\u2018', "'")
            .replace('\u2013', '-')   # En-dash → trattino
            .replace('\u2014', '-')   # Em-dash → trattino
            .replace('\u2010', '-')   # Hyphen → trattino
            .replace('\u2011', '-')   # Non-breaking hyphen → trattino
            .replace('\u2012', '-')   # Figure dash → trattino
            .replace('\u2212', '-')   # Minus sign → trattino
            .replace('\u00A0', ' ')   # Non-breaking space → spazio
            .replace('\u2026', '...')
        )

        candidate = re.sub(r'^```(?:json)?\s*\n?', '', candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r'\n?```$', '', candidate, flags=re.DOTALL).strip()

        # ✅ FIX: Rimuovi due punti duplicati (es. "key":  :  → "key": )
        candidate = re.sub(r':\s*:\s*', ':', candidate)
        # ✅ FIX: Rimuovi due punti multipli (es. "key"::: → "key":)
        candidate = re.sub(r':\s*:', ':', candidate)

        first_brace = candidate.find('{')
        if first_brace >= 0:
            extracted = self._extract_balanced_json(candidate[first_brace:])
            if extracted:
                candidate = extracted
            else:
                candidate = candidate[first_brace:]

        candidate = self._strip_json_comments(candidate)

        # Heuristic: se i commenti hanno "mangiato" la chiusura, bilancia le graffe.
        open_braces = candidate.count('{')
        close_braces = candidate.count('}')
        if open_braces > close_braces:
            candidate += '}' * (open_braces - close_braces)

        candidate = self._strip_trailing_commas(candidate)
        return candidate.strip()

    def _fix_malformed_keys(self, json_str: str) -> str:
        """
        Fixa chiavi JSON malformate comuni con Gemma:
        - "cmdtris" → "cmd1", "cmdhtml" → "cmd1", "cmdcss" → "cmd2"
        - Chiavi con due punti dentro le virgolette: "cmdhmtl:" → "cmdhmtl"
        - Chiavi con pattern non standard ma contenenti 'cmd'
        """
        # Pattern per trovare chiavi che contengono 'cmd' ma non sono cmdN
        def fix_key(match):
            full_match = match.group(0)
            key = match.group(1)
            # Rimuovi due punti finali dalla chiave se presente
            key = key.rstrip(':')
            # Se la chiave contiene 'cmd' ma non è cmdN, rinominala
            if 'cmd' in key.lower() and not re.match(r'^cmd\d+$', key, re.IGNORECASE):
                # Estrai il numero se presente
                num_match = re.search(r'\d+', key)
                if num_match:
                    num = num_match.group(0)
                    return f'"cmd{num}":'
                else:
                    # Conta quante chiavi cmd ci sono già per assegnare un numero
                    existing_cmds = re.findall(r'"cmd\d+"', json_str)
                    new_num = len(existing_cmds) + 1
                    return f'"cmd{new_num}":'
            return f'"{key}":'

        # Trova e fixa le chiavi malformate - pattern più aggressivo
        json_str = re.sub(r'"([^"]*cmd[A-Za-z_]*:?)"\s*:', fix_key, json_str, flags=re.IGNORECASE)
        
        # Pattern aggiuntivo per chiavi che iniziano con "cmd" seguito da testo
        json_str = re.sub(r'"(cmd[A-Za-z]+)"\s*:', fix_key, json_str, flags=re.IGNORECASE)

        return json_str

    def _extract_commands_from_data(self, data: dict, raw_response: str) -> ParsedCommand:
        """Converte un dict JSON nel formato ParsedCommand."""
        if not isinstance(data, dict):
            return ParsedCommand([], raw_response, False, "JSON non è un oggetto")

        commands = []

        if "command" in data and isinstance(data["command"], str):
            commands.append(self._clean_command(data["command"]))

        def _cmd_index(key: str) -> int:
            match = re.search(r'\d+', key)
            return int(match.group(0)) if match else 10_000

        cmd_keys = sorted(
            [k for k in data.keys() if re.fullmatch(r'cmd\d+', k, re.IGNORECASE)],
            key=_cmd_index
        )
        for key in cmd_keys:
            if isinstance(data[key], str):
                commands.append(self._clean_command(data[key]))

        # Fallback: tollera chiavi quasi-cmd (es. cm2, new1, command2)
        loose_cmd_keys = sorted(
            [
                k for k, v in data.items()
                if k not in cmd_keys
                and isinstance(v, str)
                and re.fullmatch(r'[A-Za-z_]*\d+[A-Za-z_]*', k)
            ],
            key=_cmd_index
        )
        for key in loose_cmd_keys:
            commands.append(self._clean_command(data[key]))

        if commands:
            return ParsedCommand(commands, raw_response, True)

        mode_value = data.get("mode")
        if isinstance(mode_value, str) and mode_value.strip():
            return ParsedCommand(
                [],
                raw_response,
                False,
                f"Formato incompleto: mode='{mode_value.strip()}' senza cmd1/cmd2"
            )

        return ParsedCommand([], raw_response, False, "Nessun comando trovato nel JSON")

    def _prefer_manual_if_richer(self, parsed: ParsedCommand, raw_response: str) -> ParsedCommand:
        """Se il parsing JSON produce pochi comandi, preferisci l'estrazione manuale se migliore."""
        if not parsed.is_valid or len(parsed.commands) > 1:
            return parsed

        manual_commands = self._extract_commands_manually(raw_response)
        if not manual_commands:
            return parsed

        manual_commands = [self._clean_command(cmd) for cmd in manual_commands if cmd and cmd.strip()]
        if len(manual_commands) > len(parsed.commands):
            return ParsedCommand(manual_commands, raw_response, True)

        return parsed

    def _try_parse_json(self, json_str: str, raw_response: str) -> ParsedCommand:
        logger.debug(f"CommandParser._try_parse_json called with json_str length {len(json_str)}")
        mode_only_error = None

        # 1. Prova parsing diretto (anche su variante normalizzata)
        normalized_json = self._normalize_json_candidate(json_str)
        candidates = [json_str]
        if normalized_json and normalized_json != json_str:
            logger.debug("CommandParser _normalize_json_candidate produced a new candidate")
            candidates.append(normalized_json)

        parse_error = None
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                parsed = self._extract_commands_from_data(data, raw_response)
                if parsed.is_valid:
                    return self._prefer_manual_if_richer(parsed, raw_response)
                if parsed.error and parsed.error.startswith("Formato incompleto: mode="):
                    mode_only_error = parsed.error
            except json.JSONDecodeError as e:
                parse_error = e

        if parse_error:
            logger.debug(f"CommandParser direct JSON decode failed: {parse_error}")

        base_json = normalized_json or json_str

        # 1b. Fixa chiavi malformate (es. "cmdtris" → "cmd1", "cmdhmtl:" → "cmd1")
        fixed_keys = self._fix_malformed_keys(base_json)
        if fixed_keys != base_json:
            logger.debug("CommandParser _fix_malformed_keys modified the json string")
            try:
                data = json.loads(fixed_keys)
                parsed = self._extract_commands_from_data(data, raw_response)
                if parsed.is_valid:
                    return self._prefer_manual_if_richer(parsed, raw_response)
            except:
                pass
            base_json = fixed_keys

        # 2. Fixa stringhe non chiuse (quando LLM non chiude prima di cmd successivo)
        fixed_unclosed = self._fix_unclosed_strings_json(base_json)
        if fixed_unclosed != base_json:
            logger.debug("CommandParser _fix_unclosed_strings_json modified the json string")
        try:
            data = json.loads(fixed_unclosed)
            parsed = self._extract_commands_from_data(data, raw_response)
            if parsed.is_valid:
                return self._prefer_manual_if_richer(parsed, raw_response)
            if parsed.error and parsed.error.startswith("Formato incompleto: mode="):
                mode_only_error = parsed.error
        except:
            pass

        # 3. Fixa PowerShell escapes
        fixed_ps = self._fix_powershell_string_escapes(fixed_unclosed)
        if fixed_ps != fixed_unclosed:
            logger.debug("CommandParser _fix_powershell_string_escapes modified the json string")
        try:
            data = json.loads(fixed_ps)
            parsed = self._extract_commands_from_data(data, raw_response)
            if parsed.is_valid:
                return self._prefer_manual_if_richer(parsed, raw_response)
            if parsed.error and parsed.error.startswith("Formato incompleto: mode="):
                mode_only_error = parsed.error
        except:
            pass

        # 4. Prova a fixare newline non escapeati
        fixed_newlines = self._fix_newline_in_string_json(fixed_ps)
        if fixed_newlines != fixed_ps:
            logger.debug("CommandParser _fix_newline_in_string_json modified the json string")
            try:
                data = json.loads(fixed_newlines)
                parsed = self._extract_commands_from_data(data, raw_response)
                if parsed.is_valid:
                    return self._prefer_manual_if_richer(parsed, raw_response)
                if parsed.error and parsed.error.startswith("Formato incompleto: mode="):
                    mode_only_error = parsed.error
            except:
                pass

        # 5. Ultimo tentativo: estrazione manuale con regex
        logger.debug("CommandParser falling back to _extract_commands_manually")
        manual_commands = self._extract_commands_manually(raw_response)
        if manual_commands:
            manual_commands = [self._clean_command(cmd) for cmd in manual_commands]
            return ParsedCommand(manual_commands, raw_response, True)

        if mode_only_error:
            logger.error(f"CommandParser mode-only response: {mode_only_error}")
            return ParsedCommand([], raw_response, False, mode_only_error)

        logger.error("CommandParser failed to parse any commands")
        return ParsedCommand([], raw_response, False, "JSON non valido")

    def _clean_command(self, cmd: str) -> str:
        """
        Pulisce il comando da caratteri di escape e quote di troppo.
        """
        # Ripristina tab letterali eventualmente introdotti da escape JSON (\t)
        cmd = cmd.replace('\t', '\\t')

        # ✅ FIX CRITICO: Normalizza punteggiatura tipografica - INCLUDI EN-DASH PRIMA
        # L'en-dash (U+2013) e em-dash (U+2014) devono diventare trattini normali
        # Questo è fondamentale per comandi PowerShell: -ItemType, -Force, ecc.
        cmd = (
            cmd
            .replace('\u201c', '"')
            .replace('\u201d', '"')
            .replace('\u201e', '"')
            .replace('\u201f', '"')
            .replace('\u2019', "'")
            .replace('\u2018', "'")
            .replace('\u2013', '-')  # En-dash → trattino normale
            .replace('\u2014', '-')  # Em-dash → trattino normale
            .replace('\u2010', '-')  # Hyphen → trattino normale
            .replace('\u2011', '-')  # Non-breaking hyphen → trattino normale
            .replace('\u2012', '-')  # Figure dash → trattino normale
            .replace('\u2212', '-')  # Minus sign → trattino normale
            .replace('\u00A0', ' ')  # Non-breaking space → space normale
            .replace('\u00B7', '')   # Middle dot → rimuovi
            .replace('\u2026', '...')  # Ellipsis → tre punti
        )
        
        # ✅ FIX: Rimuovi spazi multipli (spesso causati da en-dash + spazio)
        cmd = re.sub(r' {2,}', ' ', cmd)

        # ✅ FIX CRITICO: Rimuovi virgole extra DOPO la chiusura virgoletta
        # Pattern: "...',\n"  ->  "..."
        # Questo succede quando LLM mette virgole PowerShell-style alla fine
        cmd = re.sub(r"'\s*,\s*\n?\s*$", "'", cmd)
        cmd = re.sub(r"'\s*,\s*$", "'", cmd)
        
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

        # Heuristic: chiudi quote sbilanciate (frequente con output LLM troncati)
        if cmd.count("'") % 2 != 0:
            cmd += "'"
        elif cmd.count('"') % 2 != 0:
            cmd += '"'


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
        # Pattern tollerante: "cmdN"/"cm2"/"new1": "contenuto"
        import re
        commands = {}
        
        # Estrai il blocco JSON se dentro markdown
        block_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if block_match:
            json_str = block_match.group(0)
        
        # Trova tutte le chiavi simili a comandi numerati
        cmd_pattern = r'"([A-Za-z_]*\d+[A-Za-z_]*)"\s*:\s*"((?:[^"\\]|\\.)*)"'
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
        Estrae comandi manualmente quando il JSON e troppo malformato.
        Tollerante a smart quotes, chiavi non standard (es. cm2/new1/cmdtris) e comandi su una sola riga.
        """
        commands: List[str] = []
        if not response:
            return commands

        normalized = (
            response
            .replace('\u201c', '"')
            .replace('\u201d', '"')
            .replace('\u201e', '"')
            .replace('\u201f', '"')
            .replace('\u2019', "'")
            .replace('\u2018', "'")
            .replace('\u2013', '-')   # En-dash → trattino
            .replace('\u2014', '-')   # Em-dash → trattino
            .replace('\u2010', '-')   # Hyphen → trattino
            .replace('\u2011', '-')   # Non-breaking hyphen → trattino
            .replace('\u2012', '-')   # Figure dash → trattino
            .replace('\u2212', '-')   # Minus sign → trattino
            .replace('\u00A0', ' ')   # Non-breaking space → spazio
            .replace('\u2026', '...')
        )

        # ✅ FIX: Rimuovi due punti duplicati
        normalized = re.sub(r':\s*:\s*', ':', normalized)

        # Prima estrai il code block JSON se presente
        block_match = re.search(
            r'```(?:json)?\s*\n?({.*?})\s*\n?```',
            normalized,
            re.DOTALL | re.IGNORECASE
        )
        if block_match:
            normalized = block_match.group(1)

        # ✅ Pattern migliorato: cerca chiavi che contengono 'cmd' o sono simili a comandi
        # Supporta: cmd1, cmdtris, cmdhtml, cm2, new1, command1, fix1, ecc.
        key_pattern = re.compile(
            r'["\']?([A-Za-z_]*cmd[A-Za-z_]*|[A-Za-z_]*\d+[A-Za-z_]*)["\']?\s*:\s*["\']',
            re.IGNORECASE
        )
        matches = list(key_pattern.finditer(normalized))

        for i, match in enumerate(matches):
            value_start = match.end()
            value_end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
            cmd_str = normalized[value_start:value_end].strip()

            # Pulisci chiusure JSON e delimitatori finali
            cmd_str = re.sub(r'["\']\s*,?\s*$', '', cmd_str)
            cmd_str = cmd_str.rstrip('}').rstrip().rstrip(',').rstrip()
            cmd_str = re.sub(r'["\']\s*$', '', cmd_str)

            # Unescape base
            cmd_str = (
                cmd_str
                .replace('\\"', '"')
                .replace('\\\\', '\\')
            )

            if cmd_str:
                # Rimuovi EOF finale dagli heredoc shell
                cmd_str = re.sub(r'\n\s*EOF\s*$', '', cmd_str)
                cmd_str = re.sub(r'\n\s*EOF"\s*$', '', cmd_str)
                commands.append(cmd_str.strip())

        # ✅ Fallback aggiuntivo: se ancora nessun comando trovato, cerca pattern "parola": "valore"
        if not commands:
            fallback_pattern = re.compile(r'["\']?(\w+)["\']?\s*:\s*["\']([^"\']+)["\']', re.DOTALL)
            for match in fallback_pattern.finditer(normalized):
                key = match.group(1)
                value = match.group(2)
                # Ignora chiavi che non sembrano comandi
                if key.lower() not in ('mode', 'action', 'type', 'plan', 'explanation', 'text'):
                    value = value.replace('\\"', '"').replace('\\\\', '\\')
                    if value.strip() and len(value.strip()) > 5:  # Ignora valori troppo corti
                        commands.append(value.strip())

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

