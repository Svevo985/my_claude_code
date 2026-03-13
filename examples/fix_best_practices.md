# Best Practices per Fix e Nuove Funzionalità

## Come il bridge gestisce i progetti

Dopo ogni esecuzione di comandi, il bridge:
1. **Genera automaticamente CLAUDE.md** con l'elenco delle funzioni/metodi rilevati
2. **Mappa ogni funzione** al file di appartenenza e riga
3. **Usa questo contesto** per fix mirati successivi

## Linguaggi supportati

| Linguaggio | Estensioni | Estrazione funzioni | Fix automatico | Test |
|------------|------------|---------------------|----------------|------|
| JavaScript | .js | ✅ | ✅ | ✅ (node) |
| Python | .py | ✅ | ✅ | ✅ (python3) |
| Java | .java, .class | ✅ | ✅ | ✅ (javac + java) |
| HTML | .html | ✅ (structure) | ✅ | - |
| Shell | .sh | ✅ | ✅ | ✅ (bash) |
| CSS | .css | - | ✅ | - |

## Come chiedere fix mirati (senza che l'LLM riscriva tutto)

### ❌ Modo sbagliato (causa riscrittura completa)
```
"Fixa il bug nella modalità computer"
```
Troppo vago - l'LLM non sa quale funzione modificare.

### ✅ Modo corretto (fix mirato su funzione specifica)
```
"Fixa la funzione computerMove in tris.js: non aggiorna la UI dopo la mossa"
```
L'LLM:
1. Cerca `computerMove` nel progetto
2. Trova il file e la riga
3. Passa all'LLM solo quella funzione come contesto
4. Genera un comando heredoc per riscrivere SOLO quella funzione

## Esempi per linguaggio

### JavaScript
```
"Fixa initBoard in tris.js: dopo aver creato le celle, aggiungi cell.addEventListener('click', handleCellClick)"
```

### Python
```
"Fixa check_win in tris.py: la funzione non controlla le diagonali, aggiungi il controllo per [0,4,8] e [2,4,6]"
```

### Java
```
"Fixa il metodo computerMove in Tris.java: dopo board[moveIndex] = 'O', aggiungi l'aggiornamento della UI"
```

Per Java, il bridge:
- Estrae metodi con pattern: `public void methodName()`, `private static int calculate()`, ecc.
- Riconosce costruttori: `public ClassName()`
- Fixa punto e virgola mancanti
- Fixa parentesi graffe malformate

### HTML
```
"Aggiungi in index.html un nuovo div con id='score' dopo il board"
```

## Struttura del CLAUDE.md generato automaticamente

```markdown
# Progetto tris

## tris.js
Percorso: `tris.js`

### Funzioni implementate:
- [v] `initBoard` (riga 19)
  ```
  function initBoard() {
      boardElement.innerHTML = '';
      ...
  ```
- [v] `computerMove` (riga 84)
  ```
  function computerMove() {
      const emptyCells = ...
  ```

## Main.java
Percorso: `Main.java`

### Metodi implementati:
- [v] `main` (riga 10)
  ```
  public static void main(String[] args) {
      ...
  ```
- [v] `computerMove` (riga 45)
  ```
  private static int[] computerMove(char[][] board) {
      ...
  ```
```

## Comandi utili

| Comando | Descrizione |
|---------|-------------|
| `/context` | Mostra CLAUDE.md corrente |
| `/test` | Toggle auto-test |
| `/auto` | Toggle auto-continue |

## Fix automatico per linguaggio

### Python
- Print con spazi extra
- Parentesi mancanti
- Backslash doppi
- Caratteri unicode strani

### Java
- System.out.println con spazi
- Punto e virgola mancanti
- Parentesi graffe malformate
- Backslash doppi

### JavaScript/Shell
- Backslash doppi
- Escape sequence

## Se l'LLM continua a riscrivere tutto

1. **Sii più specifico**: "Modifica SOLO la funzione X, non tocc altro"
2. **Specifica il file**: "In Tris.java, riga N, ..."
3. **Usa il contesto**: Il bridge già passa il contesto giusto se menzioni una funzione
