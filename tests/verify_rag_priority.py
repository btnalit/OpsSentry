import os
import shutil
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.getcwd())

from src.knowledge_core import KnowledgeCore

TEMP_KNOWLEDGE_PATH = Path("data/knowledge_temp")

def setup_temp_knowledge():
    if TEMP_KNOWLEDGE_PATH.exists():
        shutil.rmtree(TEMP_KNOWLEDGE_PATH)
    TEMP_KNOWLEDGE_PATH.mkdir(parents=True)

    # 1. Manual Knowledge (Higher Priority)
    manual_content = """# Disk Cleanup Guide (Manual)
priority_score: 1.0

This is a manually written guide for disk cleanup. 
Use `rm -rf /tmp/*` to clean temp files.
"""
    (TEMP_KNOWLEDGE_PATH / "manual_cleanup.md").write_text(manual_content, encoding="utf-8")

    # 2. Auto Knowledge (Lower Priority)
    auto_content = """# Disk Cleanup Flow (Auto)
priority_score: 0.5

Automated runbook for disk cleanup. 
Found that cleaning /tmp/ improves space.
"""
    (TEMP_KNOWLEDGE_PATH / "auto_cleanup.md").write_text(auto_content, encoding="utf-8")

def verify_priority():
    print("--- Verifying RAG Priority Scoring ---")
    setup_temp_knowledge()
    
    core = KnowledgeCore(TEMP_KNOWLEDGE_PATH)
    
    # Both files contain "disk cleanup"
    results = core.search("disk cleanup", limit=5)
    
    print(f"Search results for 'disk cleanup':")
    for i, hit in enumerate(results):
        print(f"  {i+1}. {hit.chunk.source_path} (Score: {hit.score:.4f}, Priority: {hit.chunk.priority_score})")

    if len(results) < 2:
        print("[AUDIT FAIL] Expected at least 2 results.")
        return

    top_hit = results[0]
    if "manual_cleanup.md" in top_hit.chunk.source_path:
        print("[AUDIT PASS] Manual knowledge (1.0) correctly ranked above Auto knowledge (0.5).")
    else:
        print("[AUDIT FAIL] Auto knowledge ranked above Manual knowledge despite lower priority score.")

    # Cleanup
    shutil.rmtree(TEMP_KNOWLEDGE_PATH)

if __name__ == "__main__":
    verify_priority()
