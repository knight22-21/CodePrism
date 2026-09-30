"""Cross-file reference resolution, import-aware for Python calls.

Parsers that record *how* a call was made (``UnresolvedRef.call_style``) get
import-aware resolution; everything else is linked by name, as before.

For Python:

* ``f()``        follows the caller's import of ``f`` into the module it names
                 (or into that package, for re-exports from ``__init__``).
                 A builtin or a name imported from a third-party module is
                 not linked to anything in the project.
* ``mod.f()``    resolves ``mod`` through the caller's imports; a third-party
                 module (``os.path``, ``json``) is not linked.
* ``obj.f()``,   the receiver's type is unknown, so only definitions in files
  ``self.f()``   the caller imports are considered, and only a unique one is
                 linked (a guess between several would be a wrong edge).

Precision is preferred over recall: a missing edge makes an agent look
further; a wrong one sends it to the wrong code.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..core.models import EdgeKind, EdgeRecord
from ..core.storage import StorageManager
from ..parser.base import UnresolvedRef


class ModuleIndex:
    """Maps Python module names to indexed files."""

    def __init__(self, paths: list[str]) -> None:
        self._by_parts: dict[tuple[str, ...], list[str]] = {}
        for p in paths:
            parts = Path(p).with_suffix("").parts
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                self._by_parts.setdefault(parts[i:], []).append(p)

    def resolve(self, module: str, caller: str) -> list[str]:
        if not module:
            return []
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            base = Path(caller).parent.parts
            if level > 1:
                base = base[: len(base) - (level - 1)]
            rest = tuple(p for p in module.lstrip(".").split(".") if p)
            full = base + rest
            return [f for f in self._by_parts.get(full, []) if _module_parts(f) == full]
        return list(self._by_parts.get(tuple(module.split(".")), []))


# (db path, files signature) -> ModuleIndex. Building the index walks every
# Python file, so single-file updates reuse it until files are added/removed.
_MODULE_CACHE: dict[tuple[str, tuple[int, int]], ModuleIndex] = {}


async def _module_index(storage: StorageManager) -> ModuleIndex:
    key = (str(getattr(storage, "_db_path", id(storage))), await storage.files_signature())
    index = _MODULE_CACHE.get(key)
    if index is None:
        index = ModuleIndex(await storage.file_paths("python"))
        if len(_MODULE_CACHE) >= 8:
            _MODULE_CACHE.clear()
        _MODULE_CACHE[key] = index
    return index


def _module_parts(path: str) -> tuple[str, ...]:
    parts = Path(path).with_suffix("").parts
    return parts[:-1] if parts and parts[-1] == "__init__" else parts


def _package_prefixes(files: list[str]) -> tuple[str, ...]:
    """Directory prefixes ("pkg/") of the packages among *files* (their __init__.py)."""
    return tuple(str(Path(f).parent) + os.sep for f in files if f.endswith(("__init__.py",)))


def _pick(candidates: list[tuple[str, str]], files: list[str], from_id: str) -> str | None:
    """The single definition in *files* (then inside their packages), or None."""
    wanted = set(files)
    exact = {sid for sid, p in candidates if sid != from_id and p in wanted}
    if len(exact) == 1:
        return next(iter(exact))
    if exact:
        return None
    prefixes = _package_prefixes(files)
    if not prefixes:
        return None
    nested = {sid for sid, p in candidates if sid != from_id and p.startswith(prefixes)}
    return next(iter(nested)) if len(nested) == 1 else None


def _edge(ref: UnresolvedRef, target_id: str) -> EdgeRecord:
    return EdgeRecord.create(
        kind=ref.kind,
        from_id=ref.from_id,
        to_id=target_id,
        file_path=ref.file_path,
        line_number=ref.line_number,
    )


async def resolve_refs(storage: StorageManager, refs: list[UnresolvedRef]) -> list[EdgeRecord]:
    """Resolve cross-file refs to edges (refs that stay unresolved are dropped)."""
    styled = [r for r in refs if r.kind == EdgeKind.CALLS and r.call_style]
    legacy = [r for r in refs if not (r.kind == EdgeKind.CALLS and r.call_style)]

    edges: list[EdgeRecord] = []
    if legacy:
        # name -> id for just the referenced names; non-import symbols win on
        # collision so calls point at the definition, not the import stub.
        name_to_id = await storage.resolve_symbol_names({r.ref_name for r in legacy})
        for ref in legacy:
            target = name_to_id.get(ref.ref_name)
            if target and target != ref.from_id:
                edges.append(_edge(ref, target))
    if styled:
        edges.extend(await _resolve_python_calls(storage, styled))
    return edges


async def _resolve_python_calls(
    storage: StorageManager, refs: list[UnresolvedRef]
) -> list[EdgeRecord]:
    defs = await storage.definitions_by_name({r.ref_name for r in refs})
    imports = await storage.imports_by_file({r.file_path for r in refs})
    modules = await _module_index(storage)
    imported_files_cache: dict[str, list[str]] = {}

    def imported_files(caller: str) -> list[str]:
        if caller not in imported_files_cache:
            files: list[str] = []
            for name, mod in imports.get(caller, []):
                if name.endswith(".*"):
                    files += modules.resolve(mod, caller)
                    continue
                files += modules.resolve(mod, caller)
                if name != mod:  # from pkg import submodule
                    files += modules.resolve(_join(mod, name), caller)
            imported_files_cache[caller] = sorted(set(files))
        return imported_files_cache[caller]

    edges: list[EdgeRecord] = []
    for ref in refs:
        candidates = defs.get(ref.ref_name)
        if not candidates:
            continue
        imps = imports.get(ref.file_path, [])
        if ref.call_style == "bare":
            files = _bare_call_files(ref, imps, modules)
        else:
            files = _attribute_call_files(ref, imps, modules)
            if files is None:  # receiver type unknown: only what the caller imports
                files = imported_files(ref.file_path)
        if not files:
            continue
        target = _pick(candidates, files, ref.from_id)
        if target:
            edges.append(_edge(ref, target))
    return edges


def _join(module: str, name: str) -> str:
    return module + name if module.endswith(".") else f"{module}.{name}"


def _bare_call_files(ref: UnresolvedRef, imps, modules: ModuleIndex) -> list[str]:
    """Files ``f()`` can refer to: via ``from m import f`` / ``import f``, or a star import."""
    for name, mod in imps:
        if name == ref.ref_name:
            return modules.resolve(mod, ref.file_path)
    files: list[str] = []
    for name, mod in imps:
        if name.endswith(".*"):
            files += modules.resolve(mod, ref.file_path)
    # Not imported and not defined in this file (intra-file refs are resolved
    # by the parser): a builtin or a global we can't see. Link nothing.
    return files


def _attribute_call_files(ref: UnresolvedRef, imps, modules: ModuleIndex) -> list[str] | None:
    """Files ``recv.f()`` can refer to when ``recv`` is an imported module.

    Returns [] for a third-party module (link nothing) and None when the
    receiver isn't a module the caller imported (the type is unknown).
    """
    if not ref.receiver:
        return None
    head, _, rest = ref.receiver.partition(".")
    if head in ("self", "cls"):
        return None
    tail = f".{rest}" if rest else ""
    for name, mod in imps:
        if name == mod:  # import a.b  -> binds "a"
            if head == name.split(".")[0]:
                return modules.resolve(head + tail, ref.file_path)
        elif name == head:  # import m as head / from pkg import head
            files = modules.resolve(_join(mod, head) + tail, ref.file_path)
            if not files:
                files = modules.resolve(mod + tail, ref.file_path)
            return files
    return None
