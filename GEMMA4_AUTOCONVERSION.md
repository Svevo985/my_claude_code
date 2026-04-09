# Gemma 4 ShellBot Auto-Conversion Guide

## Overview
The Ollama File System Bridge now automatically detects Gemma 4 models and creates specialized shellbot variants with optimized parameters.

## What's New

### 1. Gemma 4 Detection
The system automatically identifies Gemma 4 models by checking for:
- `gemma4`
- `gemma-4`
- `gemma:4`
- `gemma4:`

### 2. Optimized Parameters for Gemma 4
Gemma 4 gets specialized tuning that differs from the default phi4-mini settings:

| Parameter | Default (phi4-mini) | Gemma 4 | Reason |
|-----------|---------------------|---------|--------|
| `num_batch` | 512 | **1024** | Gemma handles larger batches better |
| `num_ctx` | 8192 | **16384** | Larger context for complex projects |
| `temperature` | 0.1 | **0.15** | Slightly higher for balanced creativity |
| `top_p` | 0.9 | **0.92** | More controlled variety |
| `top_k` | 40 | **50** | More options but controlled |
| `repeat_penalty` | 1.15 | **1.10** | Less aggressive (Gemma is already coherent) |
| `repeat_last_n` | 64 | **128** | Longer repetition memory |

### 3. Gemma 4 Specific Stop Tokens
The system uses Gemma's native stop tokens:
- `<end_of_turn>`
- `<start_of_turn>`
- `</s>`

### 4. Auto-Conversion Process

When you run the bridge, it will:

1. **Detect** `gemma:latest` in your installed models
2. **Load** the appropriate Gemma 4 template based on mode:
   - `/new` or `/fix` → `Modelfile_gemma4_create`
   - `/reverse` → `Modelfile_gemma4_docs`
   - Default → `Modelfile_gemma4`
3. **Create** `gemma-latest-shellbot:latest` with optimized params
4. **Use** the new shellbot for file operations

### 5. Generated Model Name
From `gemma:latest` → `gemma-latest-shellbot:latest`

## Usage

### Automatic
Just start the bridge - it will auto-convert if needed:
```bash
python main.py
```

### Manual Rebuild
Force rebuild all shellbot models (including Gemma 4):
```
/rebuild
```

### Check Available Models
```bash
ollama list
```

You should see:
- `gemma:latest` (original)
- `gemma-latest-shellbot:latest` (auto-generated)

## Modelfile Templates

Three specialized templates are available:

### 1. Modelfile_gemma4 (Base)
General-purpose file system bridge with balanced parameters.

### 2. Modelfile_gemma4_create (For /new and /fix)
Optimized for code creation and bug fixing with:
- `num_predict: 4096` for long code generation
- `temperature: 0.15` for deterministic JSON

### 3. Modelfile_gemma4_docs (For /reverse)
Optimized for documentation generation with:
- `temperature: 0.2` for more creative documentation
- Same context window for comprehensive analysis

## Troubleshooting

### Model Not Created
If `gemma-latest-shellbot:latest` doesn't appear:
1. Check logs: `logs/ollama_*.log`
2. Verify Gemma 4 is installed: `ollama list | grep gemma`
3. Force rebuild: `/rebuild`

### Wrong Template Used
The system logs which template is loaded. Check:
```
logs/ollama_*.log
```
Look for: "🎯 Rilevato Gemma 4 - uso template specifici"

### Performance Issues
If Gemma 4 is slow or runs out of memory:
- Reduce `num_ctx` from 16384 to 8192
- Reduce `num_batch` from 1024 to 512
- Edit `modelfiles/Modelfile_gemma4*` files

## Technical Details

### Code Changes in main.py

1. **`_is_gemma4_model(model)`** - Detects Gemma 4 variants
2. **`_load_template_modelfile(base_model)`** - Loads model-specific templates
3. **`_shellbot_target_name(model)`** - Generates proper target name
4. **`_auto_convert_models()`** - Passes base_model for template selection

### File Structure
```
modelfiles/
├── Modelfile_gemma4           # Base template
├── Modelfile_gemma4_create    # For /new and /fix
├── Modelfile_gemma4_docs      # For /reverse
├── Modelfile_windows          # Default Windows template
└── ...
```

## Benefits Over Generic Template

1. **Better JSON Output** - Tuned parameters reduce JSON syntax errors
2. **Larger Context** - Can handle bigger projects in one go
3. **Native Stop Tokens** - Respects Gemma's conversation format
4. **Optimized Performance** - Balanced for speed vs quality
5. **Mode-Specific** - Different templates for different tasks

## Next Steps

1. Start the bridge: `python main.py`
2. Switch to Gemma 4: `/model gemma:latest`
3. The system will auto-create `gemma-latest-shellbot:latest`
4. Use normally - it will use the Gemma 4 shellbot

---

**Created:** 2026-04-07
**Version:** 1.0
