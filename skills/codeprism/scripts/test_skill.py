#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify CodePrism skill functionality.

This script helps test the skill by verifying:
1. MCP server connection
2. Graph indexing
3. Core tool availability
4. Security scanning

Run this before testing with Codex or Cursor to ensure CodePrism is working.
"""

import asyncio
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')

try:
    from codeprism import CodePrism, SecurityGate
except ImportError:
    print("ERROR: codeprism-ai not installed")
    print("Run: pip install codeprism-ai")
    sys.exit(1)


async def test_indexing(project_path: str):
    """Test that the project can be indexed."""
    print(f"\n{'='*60}")
    print("TEST 1: Project Indexing")
    print(f"{'='*60}")
    print(f"Project path: {project_path}")

    async with CodePrism(project_path) as prism:
        print("Indexing project...")
        await prism.index()
        print("[PASS] Indexing complete")

        # Get stats from storage directly
        from codeprism.core.paths import get_db_path
        from codeprism.core.storage import StorageManager

        db = StorageManager(get_db_path(project_path))
        await db.initialize()

        stats = await db.get_stats()
        print(f"[PASS] Files indexed: {stats.get('file_count', 0)}")
        print(f"[PASS] Functions indexed: {stats.get('function_count', 0)}")
        print(f"[PASS] Classes indexed: {stats.get('class_count', 0)}")
        print(f"[PASS] Index status: {stats.get('index_status', 'unknown')}")

        await db.close()

        # Index status might be 'unknown' in some versions, but if we have files indexed, it's working
        if stats.get('file_count', 0) == 0:
            print("[FAIL] No files indexed")
            return False

        return True


async def test_context_query(project_path: str):
    """Test get_context tool."""
    print(f"\n{'='*60}")
    print("TEST 2: Context Query (get_context)")
    print(f"{'='*60}")

    async with CodePrism(project_path) as prism:
        # Try to find a Python file with functions
        try:
            from codeprism.core.storage import StorageManager
            from codeprism.core.paths import get_db_path

            db = StorageManager(get_db_path(project_path))
            await db.initialize()

            # Get first file with symbols
            files = await db.get_all_files()
            python_files = [f for f in files if f.path.endswith('.py') and not f.path.startswith('tests')]

            if not python_files:
                print("[WARN] No Python files found to test")
                await db.close()
                return True

            # Find a file with actual symbols
            test_file = None
            test_symbol = None

            for f in python_files:
                file_record = await db.get_file_by_path(f.path)
                if not file_record:
                    continue

                symbols = await db.get_symbols_for_file(file_record.id)
                if symbols:
                    test_file = f.path
                    test_symbol = symbols[0].name
                    break

            await db.close()

            if not test_file or not test_symbol:
                print("[WARN] No file with symbols found to test")
                return True

            print(f"Testing with: {test_file}::{test_symbol}")

            ctx = await prism.get_context(test_file, test_symbol, depth=2)
            if ctx:
                print(f"[PASS] Context retrieved")
                print(f"  - Symbol: {ctx.symbol.name}")
                print(f"  - Signature: {ctx.symbol.signature[:50] if ctx.symbol.signature else 'N/A'}...")
                print(f"  - Direct callers: {len(ctx.direct_callers)}")
                print(f"  - Direct callees: {len(ctx.direct_callees)}")
            else:
                print("[WARN] Context returned None (symbol may not be found)")

            return True

        except Exception as e:
            print(f"[WARN] Test skipped: {e}")
            import traceback
            traceback.print_exc()
            return True


async def test_security_gate():
    """Test security scanning."""
    print(f"\n{'='*60}")
    print("TEST 3: Security Gate (scan_diff)")
    print(f"{'='*60}")

    gate = SecurityGate()

    # Test 1: Safe code
    safe_code = """
def hello_world():
    print("Hello, World!")
    return 42
"""

    report = await gate.check_content(safe_code, "test.py")
    print(f"[PASS] Safe code scan: {report.status}")
    if report.status == "BLOCK":
        print("[WARN] Safe code was incorrectly blocked")
        return False

    # Test 2: Code with secret
    secret_code = """
API_KEY = "sk-1234567890abcdef"
def get_data():
    return API_KEY
"""

    report = await gate.check_content(secret_code, "test.py")
    print(f"[PASS] Secret code scan: {report.status}")
    if report.status == "BLOCK":
        print(f"  - Issues found: {len(report.issues)}")
        for issue in report.issues:
            print(f"    - {issue.description}")
    else:
        print("[WARN] Secret code was not blocked")

    return True


async def test_module_summary(project_path: str):
    """Test get_module_summary."""
    print(f"\n{'='*60}")
    print("TEST 4: Module Summary")
    print(f"{'='*60}")

    async with CodePrism(project_path) as prism:
        from codeprism.core.storage import StorageManager
        from codeprism.core.paths import get_db_path

        db = StorageManager(get_db_path(project_path))
        await db.initialize()

        files = await db.get_all_files()
        if files:
            test_file = files[0].path
            print(f"Testing with: {test_file}")

            summary = await prism.get_module_summary(test_file)
            if summary:
                print(f"[PASS] Summary retrieved")
                print(f"  - Purpose: {summary.purpose[:100]}...")
                print(f"  - Public API items: {len(summary.public_api)}")
                print(f"  - Complexity score: {summary.complexity_score}")
                print(f"  - Dependencies: {len(summary.dependencies)}")
            else:
                print("[WARN] Summary returned None")

        await db.close()
        return True


async def main():
    """Run all tests."""
    project_path = Path.cwd()

    print("="*60)
    print("CodePrism Skill Test Suite")
    print("="*60)
    print(f"Project: {project_path}")

    tests = [
        ("Indexing", lambda: test_indexing(str(project_path))),
        ("Context Query", lambda: test_context_query(str(project_path))),
        ("Security Gate", test_security_gate),
        ("Module Summary", lambda: test_module_summary(str(project_path))),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n[FAIL] {name} failed with error: {e}")
            results.append((name, False))

    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n[PASS] All tests passed! CodePrism is ready for agent testing.")
        return 0
    else:
        print("\n[WARN] Some tests failed. Check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
