"""
Utility per scansione progetto e selezione file per reverse engineering.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Tuple, List, Set

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode",
    "node_modules", "dist", "build", "out", "target", "bin", "obj",
    ".dart_tool", ".flutter-plugins", ".flutter-plugins-dependencies",
    ".gradle", ".pub-cache", "Pods",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", ".env", ".cache", "tmp", "temp", "logs", "log", "coverage", "reports",
    ".next", ".nuxt", ".svelte-kit", ".expo", ".terraform",
    "test", "tests",
}

DEFAULT_TEXT_EXTS = {
    ".md", ".txt",
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".kt", ".swift", ".m",
    ".go", ".rs", ".cpp", ".c", ".h", ".hpp",
    ".html", ".css", ".scss", ".sass",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg",
    ".gradle", ".properties", ".sh", ".bat", ".ps1",
    ".dart",
}

IMPORTANT_FILENAMES = {
    "readme.md", "readme", "readme.txt",
    "pubspec.yaml", "pubspec.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "setup.cfg", "setup.py",
    "cargo.toml", "cargo.lock",
    "go.mod", "go.sum",
    "pom.xml", "build.gradle", "settings.gradle",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "androidmanifest.xml", "info.plist",
}

ENTRY_STEMS = {"main", "app", "index", "server", "cli", "run", "start"}
PRIMARY_DOCS = {"readme.md", "readme.txt", "readme", "claude.md", "claude"}


def _is_ignored_dir(name: str) -> bool:
    return name in DEFAULT_IGNORE_DIRS


def _is_text_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name in IMPORTANT_FILENAMES:
        return True
    ext = path.suffix.lower()
    return ext in DEFAULT_TEXT_EXTS


def _make_candidate_entry(root: Path, rel: Path) -> Tuple[Path, int, Set[str]] | None:
    full = (root / rel).resolve()
    if not full.exists() or full.is_dir():
        return None
    try:
        size = full.stat().st_size
    except Exception:
        return None
    tags: Set[str] = set()
    lname = rel.name.lower()
    stem = rel.stem.lower()
    if lname in IMPORTANT_FILENAMES or lname in PRIMARY_DOCS:
        tags.add("config")
    if stem in ENTRY_STEMS:
        tags.add("entry")
    if "src" in rel.parts or "lib" in rel.parts:
        tags.add("source")
    if full.suffix.lower() in {".md", ".txt"}:
        tags.add("doc")
    if full.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        tags.add("config")
    return (rel, size, tags)


def find_primary_docs(root: Path) -> List[Path]:
    root = root.resolve()
    found: List[Path] = []
    seen = set()
    for name in ["README.md", "readme.md", "README", "readme", "CLAUDE.md", "claude.md", "CLAUDE", "claude"]:
        p = root / name
        if p.exists() and p.is_file():
            rel = p.relative_to(root)
            key = rel.as_posix().lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(rel)
    return found


def determine_source_roots(root: Path) -> List[str]:
    root = root.resolve()
    roots: List[str] = []

    # Multi-modulo: cartelle di primo livello con src/main
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if (child / "src" / "main").exists():
                roots.append(Path(child.name) / "src" / "main")
    except Exception:
        pass

    # Pattern comuni
    common = [
        "app/src/main",  # Android
        "src/main",      # Java/Kotlin/Scala
        "src",           # generico
        "lib",           # Flutter/Ruby/Node
    ]
    for cand in common:
        if (root / cand).exists():
            roots.append(cand)

    # Fallback specifici (solo se non abbiamo trovato nulla)
    if not roots:
        for cand in ["cmd", "internal"]:
            if (root / cand).exists():
                roots.append(cand)

    # Normalizza e de-duplica preservando ordine
    seen = set()
    normalized: List[str] = []
    for r in roots:
        r_str = r.as_posix() if isinstance(r, Path) else str(r)
        r_key = r_str.replace("\\", "/").lower()
        if r_key in seen:
            continue
        seen.add(r_key)
        normalized.append(r_str.replace("\\", "/"))

    # Se esiste src/main alla root, evita src generico
    if any(r in {"src/main", "app/src/main"} for r in normalized):
        normalized = [r for r in normalized if r != "src"]

    return normalized


def _rel_starts_with(rel: Path, root_rel: str) -> bool:
    root_parts = Path(root_rel).parts
    if not root_parts:
        return False
    if len(rel.parts) < len(root_parts):
        return False
    rel_prefix = [p.lower() for p in rel.parts[:len(root_parts)]]
    root_prefix = [p.lower() for p in root_parts]
    return rel_prefix == root_prefix


def _is_config_only(tags: Set[str]) -> bool:
    return "config" in tags and "source" not in tags and "entry" not in tags and "doc" not in tags


def apply_reverse_policy(
    root: Path,
    candidates: List[Tuple[Path, int, Set[str]]],
    max_candidates: int = 40,
) -> Tuple[List[Tuple[Path, int, Set[str]]], dict]:
    root = root.resolve()
    docs = find_primary_docs(root)
    source_roots = determine_source_roots(root)

    filtered: List[Tuple[Path, int, Set[str]]] = []

    excluded_tests = 0
    excluded_config = 0
    if source_roots:
        for rel, size, tags in candidates:
            if not rel.parts:
                continue
            if not any(_rel_starts_with(rel, sr) for sr in source_roots):
                continue
            if any(p.lower() in {"test", "tests"} for p in rel.parts):
                excluded_tests += 1
                continue
            # per Java: evita src/test/*
            if len(rel.parts) >= 2 and rel.parts[0].lower() == "src" and rel.parts[1].lower() == "test":
                excluded_tests += 1
                continue
            if _is_config_only(tags):
                excluded_config += 1
                continue
            filtered.append((rel, size, tags))
    else:
        for rel, size, tags in candidates:
            if any(p.lower() in {"test", "tests"} for p in rel.parts):
                excluded_tests += 1
                continue
            if _is_config_only(tags):
                excluded_config += 1
                continue
            filtered.append((rel, size, tags))

    # Assicura presenza README/CLAUDE
    existing = {rel.as_posix() for rel, _, _ in filtered}
    for rel in docs:
        if rel.as_posix() not in existing:
            entry = _make_candidate_entry(root, rel)
            if entry:
                filtered.append(entry)
                existing.add(rel.as_posix())

    # Limita il numero di candidati se troppo alto
    limited = False
    if len(filtered) > max_candidates:
        limited = True
        filtered = _top_ranked_candidates(filtered, max_candidates)

    info = {
        "docs": [p.as_posix() for p in docs],
        "source_roots": source_roots,
        "candidates_before": len(candidates),
        "candidates_after": len(filtered),
        "excluded_tests": excluded_tests,
        "excluded_config": excluded_config,
        "limited": limited,
        "limit": max_candidates,
    }
    return filtered, info


def _is_java_service_file(rel: Path) -> bool:
    """Check if file is a Java Service class (ends with Service.java)."""
    return rel.suffix.lower() == ".java" and rel.stem.endswith("Service")


def _is_java_controller_file(rel: Path) -> bool:
    """Check if file is a Java Controller class."""
    return rel.suffix.lower() == ".java" and rel.stem.endswith("Controller")


def _is_java_repository_file(rel: Path) -> bool:
    """Check if file is a Java Repository/DAO class."""
    stem = rel.stem.lower()
    return rel.suffix.lower() == ".java" and (stem.endswith("repository") or stem.endswith("dao") or stem.endswith("mapper"))


def _is_java_dto_file(rel: Path) -> bool:
    """Check if file is a Java DTO/Request/Response class."""
    stem = rel.stem.lower()
    return rel.suffix.lower() == ".java" and (stem.endswith("dto") or stem.endswith("request") or stem.endswith("response") or stem.endswith("vo"))


def _is_java_config_file(rel: Path) -> bool:
    """Check if file is a Java Spring config class."""
    return rel.suffix.lower() == ".java" and (rel.stem.endswith("Config") or rel.stem.endswith("Configuration") or rel.stem.endswith("Application"))


def _is_java_project(candidates: List[Tuple[Path, int, Set[str]]]) -> bool:
    """Detect if project is a Java project (has .java files and pom.xml/build.gradle)."""
    has_java = any(item[0].suffix.lower() == ".java" for item in candidates)
    has_build = any(item[0].name.lower() in {"pom.xml", "build.gradle", "settings.gradle"} for item in candidates)
    return has_java and has_build


def _is_spring_boot_project(root: Path) -> bool:
    """
    Detect if project is Spring Boot by checking:
    1. pom.xml contains spring-boot-starter or @SpringBootApplication
    2. build.gradle contains springboot plugin
    """
    root = root.resolve()
    
    # Check pom.xml FIRST
    pom_path = root / "pom.xml"
    if pom_path.exists():
        try:
            pom_content = pom_path.read_text(encoding='utf-8', errors='ignore').lower()
            spring_indicators = [
                'spring-boot-starter',
                'springboot',
                'springframework.boot',
            ]
            for indicator in spring_indicators:
                if indicator in pom_content:
                    return True  # Spring Boot trovato!
        except Exception as e:
            print(f"DEBUG: Errore lettura pom.xml: {e}")
    
    # Check build.gradle
    gradle_path = root / "build.gradle"
    if gradle_path.exists():
        try:
            gradle_content = gradle_path.read_text(encoding='utf-8', errors='ignore').lower()
            if 'springboot' in gradle_content or 'spring-boot' in gradle_content:
                return True
        except:
            pass
    
    # Check main application class
    for rel, _, _ in candidates:
        if rel.name.endswith("Application.java"):
            try:
                content = (root / rel).read_text(encoding='utf-8', errors='ignore')
                if '@SpringBootApplication' in content:
                    return True
            except:
                pass
    
    return False


def find_java_service_classes(
    candidates: List[Tuple[Path, int, Set[str]]]
) -> List[Path]:
    """Find all Java Service classes in the candidate list."""
    services = []
    for rel, _, _ in candidates:
        if _is_java_service_file(rel):
            services.append(rel)
    return sorted(services, key=lambda p: p.as_posix())


def find_java_controller_classes(
    candidates: List[Tuple[Path, int, Set[str]]]
) -> List[Path]:
    """Find all Java Controller classes in the candidate list."""
    controllers = []
    for rel, _, _ in candidates:
        if _is_java_controller_file(rel):
            controllers.append(rel)
    return sorted(controllers, key=lambda p: p.as_posix())


def _candidate_score(item: Tuple[Path, int, Set[str]], is_java_project: bool = False) -> int:
    _, rel, tags = item[0], item[0], item[2]
    score = 0
    
    # Java microservice pattern: prioritize Service classes
    if is_java_project:
        if _is_java_service_file(rel):
            score += 10  # Highest priority - business logic
        elif _is_java_controller_file(rel):
            score += 8   # API endpoints
        elif _is_java_config_file(rel):
            score += 6   # Configuration
        elif _is_java_repository_file(rel):
            score += 4   # Data access
        elif _is_java_dto_file(rel):
            score += 2   # Data transfer objects
    
    # Generic scoring
    if "entry" in tags:
        score += 4
    if "config" in tags:
        score += 3
    if "source" in tags:
        score += 2
    if "doc" in tags:
        score += 1
    return score


def _top_ranked_candidates(
    candidates: List[Tuple[Path, int, Set[str]]],
    limit: int
) -> List[Tuple[Path, int, Set[str]]]:
    is_java = _is_java_project(candidates)
    ranked = sorted(candidates, key=lambda x: (-_candidate_score(x, is_java), x[0].as_posix()))
    return ranked[:limit]


def build_tree(
    root: Path,
    max_depth: int = 4,
    max_lines: int = 400,
) -> str:
    root = root.resolve()
    lines: List[str] = []
    line_count = 0
    root_name = root.name or str(root)
    lines.append(f"{root_name}/")
    line_count += 1

    def walk(cur: Path, prefix: str, depth: int):
        nonlocal line_count
        if depth > max_depth or line_count >= max_lines:
            return

        try:
            entries = list(cur.iterdir())
        except Exception:
            return

        # Filtra dir ignorate
        filtered = []
        for e in entries:
            if e.is_dir() and _is_ignored_dir(e.name):
                continue
            filtered.append(e)

        # Ordina: dir prima dei file
        filtered.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        for i, entry in enumerate(filtered):
            if line_count >= max_lines:
                break
            connector = "|--" if i < len(filtered) - 1 else "`--"
            name = entry.name + ("/" if entry.is_dir() else "")
            lines.append(f"{prefix}{connector} {name}")
            line_count += 1
            if entry.is_dir():
                extension = "|   " if i < len(filtered) - 1 else "    "
                walk(entry, prefix + extension, depth + 1)

    walk(root, "", 1)
    if line_count >= max_lines:
        lines.append("... (tree truncated)")
    return "\n".join(lines)


def build_tree_from_paths(
    rel_paths: Iterable[Path],
    root_name: str = "project",
    max_lines: int = 400,
) -> str:
    tree: dict = {}

    for rel in rel_paths:
        parts = list(rel.parts)
        if not parts:
            continue
        node = tree
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if is_last:
                node.setdefault(part, None)
            else:
                child = node.get(part)
                if child is None:
                    child = {}
                    node[part] = child
                node = child

    lines: List[str] = []
    line_count = 0
    lines.append(f"{root_name}/")
    line_count += 1

    def walk(node: dict, prefix: str):
        nonlocal line_count
        if line_count >= max_lines:
            return
        items = sorted(
            node.items(),
            key=lambda kv: (0 if isinstance(kv[1], dict) else 1, kv[0].lower()),
        )
        for i, (name, child) in enumerate(items):
            if line_count >= max_lines:
                break
            connector = "|--" if i < len(items) - 1 else "`--"
            is_dir = isinstance(child, dict)
            suffix = "/" if is_dir else ""
            lines.append(f"{prefix}{connector} {name}{suffix}")
            line_count += 1
            if is_dir:
                extension = "|   " if i < len(items) - 1 else "    "
                walk(child, prefix + extension)

    walk(tree, "")
    if line_count >= max_lines:
        lines.append("... (tree truncated)")
    return "\n".join(lines)


def collect_candidate_files(
    root: Path,
    max_files: int = 200,
    max_file_size: int = 512 * 1024,
) -> List[Tuple[Path, int, Set[str]]]:
    root = root.resolve()
    results: List[Tuple[Path, int, Set[str]]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Filtra dir ignorate in-place
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]

        for name in filenames:
            rel = Path(dirpath).resolve().relative_to(root) / name
            full = root / rel

            # Evita file troppo grandi
            try:
                size = full.stat().st_size
            except Exception:
                continue
            if size > max_file_size:
                continue

            if not _is_text_candidate(full):
                continue

            tags: Set[str] = set()
            lname = name.lower()
            stem = Path(name).stem.lower()
            if lname in IMPORTANT_FILENAMES:
                tags.add("config")
            if stem in ENTRY_STEMS:
                tags.add("entry")
            if "src" in rel.parts or "lib" in rel.parts:
                tags.add("source")
            if full.suffix.lower() in {".md", ".txt"}:
                tags.add("doc")
            if full.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
                tags.add("config")

            results.append((rel, size, tags))
            if len(results) >= max_files:
                break
        if len(results) >= max_files:
            break

    return results


def collect_candidate_files_with_stats(
    root: Path,
    max_files: int = 200,
    max_file_size: int = 512 * 1024,
) -> Tuple[List[Tuple[Path, int, Set[str]]], dict]:
    root = root.resolve()
    results: List[Tuple[Path, int, Set[str]]] = []
    stats = {
        "seen_files": 0,
        "ignored_dirs": 0,
        "ignored_ext": 0,
        "ignored_size": 0,
        "ignored_other": 0,
        "candidates": 0,
        "truncated": False,
    }

    for dirpath, dirnames, filenames in os.walk(root):
        ignored = [d for d in dirnames if _is_ignored_dir(d)]
        stats["ignored_dirs"] += len(ignored)
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]

        for name in filenames:
            stats["seen_files"] += 1
            rel = Path(dirpath).resolve().relative_to(root) / name
            full = root / rel

            try:
                size = full.stat().st_size
            except Exception:
                stats["ignored_other"] += 1
                continue

            if size > max_file_size:
                stats["ignored_size"] += 1
                continue

            if not _is_text_candidate(full):
                stats["ignored_ext"] += 1
                continue

            tags: Set[str] = set()
            lname = name.lower()
            stem = Path(name).stem.lower()
            if lname in IMPORTANT_FILENAMES:
                tags.add("config")
            if stem in ENTRY_STEMS:
                tags.add("entry")
            if "src" in rel.parts or "lib" in rel.parts:
                tags.add("source")
            if full.suffix.lower() in {".md", ".txt"}:
                tags.add("doc")
            if full.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
                tags.add("config")

            results.append((rel, size, tags))
            stats["candidates"] += 1
            if len(results) >= max_files:
                stats["truncated"] = True
                break
        if stats["truncated"]:
            break

    return results, stats


def format_candidate_index(candidates: List[Tuple[Path, int, Set[str]]]) -> Tuple[str, Set[str]]:
    lines: List[str] = []
    rel_set: Set[str] = set()
    for rel, size, tags in candidates:
        rel_posix = rel.as_posix()
        rel_set.add(rel_posix)
        kb = max(1, int(size / 1024))
        tag_str = f" [{', '.join(sorted(tags))}]" if tags else ""
        lines.append(f"- {kb} KB | {rel_posix}{tag_str}")
    return "\n".join(lines), rel_set


def pick_default_files(
    candidates: List[Tuple[Path, int, Set[str]]],
    limit: int = 10
) -> List[Path]:
    is_java = _is_java_project(candidates)
    
    # Priorita: entry + config + source, poi doc
    def score(item: Tuple[Path, int, Set[str]]) -> int:
        return _candidate_score(item, is_java)

    ranked = sorted(candidates, key=lambda x: (-score(x), x[0].as_posix()))
    return [r[0] for r in ranked[:limit]]


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def extract_requested_files(
    commands: Iterable[str],
    root: Path,
    allowed_rel: Set[str] | None = None,
    max_files: int = 15
) -> List[Path]:
    root = root.resolve()
    requested: List[Path] = []

    read_re = re.compile(r'^\s*read\s+(.+)$', re.IGNORECASE)
    cat_re = re.compile(r'\b(?:cat|type|get-content)\b\s+(?:-path\s+)?(.+)$', re.IGNORECASE)

    for cmd in commands:
        if len(requested) >= max_files:
            break
        cmd = cmd.strip()
        if not cmd:
            continue

        path_part = None
        m = read_re.match(cmd)
        if m:
            path_part = m.group(1)
        else:
            m = cat_re.search(cmd)
            if m:
                path_part = m.group(1)

        if not path_part:
            # prova a catturare una path tra virgolette
            m = re.search(r'["\']([^"\']+)["\']', cmd)
            if m:
                path_part = m.group(1)

        if not path_part:
            continue

        # rimuovi pipe/redirection
        path_part = re.split(r'[|>]', path_part)[0].strip()
        path_part = _strip_quotes(path_part)

        p = Path(path_part)
        if not p.is_absolute():
            p = (root / path_part).resolve()
        else:
            p = p.resolve()

        try:
            p.relative_to(root)
        except Exception:
            continue

        rel = p.relative_to(root)
        rel_posix = rel.as_posix()
        if allowed_rel and rel_posix not in allowed_rel:
            continue

        if rel not in requested:
            requested.append(rel)

    return requested


def read_files_content(
    root: Path,
    rel_paths: Iterable[Path],
    max_chars_per_file: int = 4000,
    max_total_chars: int = 20000,
) -> str:
    root = root.resolve()
    total = 0
    chunks: List[str] = []

    for rel in rel_paths:
        full = (root / rel).resolve()
        try:
            full.relative_to(root)
        except Exception:
            continue
        if not full.exists() or full.is_dir():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        content = content[:max_chars_per_file]
        if total + len(content) > max_total_chars:
            remaining = max_total_chars - total
            if remaining <= 0:
                break
            content = content[:remaining]

        rel_posix = rel.as_posix()
        chunks.append(f"## {rel_posix}:\n```\n{content}\n```\n")
        total += len(content)

        if total >= max_total_chars:
            break

    return "\n".join(chunks)


def read_files_content_with_stats(
    root: Path,
    rel_paths: Iterable[Path],
    max_chars_per_file: int = 4000,
    max_total_chars: int = 20000,
) -> Tuple[str, dict]:
    root = root.resolve()
    total = 0
    chunks: List[str] = []
    stats = {
        "files_read": 0,
        "total_chars": 0,
        "truncated": False,
    }

    for rel in rel_paths:
        full = (root / rel).resolve()
        try:
            full.relative_to(root)
        except Exception:
            continue
        if not full.exists() or full.is_dir():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        content = content[:max_chars_per_file]
        if total + len(content) > max_total_chars:
            remaining = max_total_chars - total
            if remaining <= 0:
                stats["truncated"] = True
                break
            content = content[:remaining]
            stats["truncated"] = True

        rel_posix = rel.as_posix()
        chunks.append(f"## {rel_posix}:\n```\n{content}\n```\n")
        total += len(content)
        stats["files_read"] += 1
        stats["total_chars"] = total

        if total >= max_total_chars:
            stats["truncated"] = True
            break

    return "\n".join(chunks), stats
