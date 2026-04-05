from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Sequence

from .ops_ledger import OpsLedger, LedgerEntry
from .knowledge_core import KnowledgeCore, SearchHit

logger = logging.getLogger(__name__)

EVOLVED_KNOWLEDGE_DIR = Path("data/knowledge/evolved")

RUNBOOK_TEMPLATE = """## Runbook: {action}
priority_score: 0.5

{description}

## Metadata
- **Source Entry ID**: {entry_id}
- **Priority Score**: {priority_score}
- **Generated At**: {generated_at}

## Context
{context}

## Execution Steps
{steps}

## Verification
{verification}

## Case Studies
- **Case {entry_id}**: {summary}
"""

CASE_STUDY_TEMPLATE = """
- **Case {entry_id}**: {summary} (Success at {updated_at})
"""

class EvolutionManager:
    def __init__(
        self, 
        ledger: OpsLedger, 
        knowledge: KnowledgeCore,
        evolved_dir: Path = EVOLVED_KNOWLEDGE_DIR,
        min_score: float = 15.0
    ) -> None:
        self.ledger = ledger
        self.knowledge = knowledge
        self.evolved_dir = evolved_dir
        self.evolved_dir.mkdir(parents=True, exist_ok=True)
        self.min_score = min_score

    def evolve_step(self, limit: int = 50) -> int:
        """
        Extract successful entries and generate/update Runbooks.
        Returns the number of Runbooks processed.
        """
        # 1. List successful entries that haven't been evolved yet
        entries = self.ledger.list_entries(status="completed")
        # Filter for entries that have enough data to be a 'process'
        meaningful_entries = [e for e in entries if e.checkpoint and len(e.checkpoint.get("steps", [])) > 1]
        
        processed_count = 0
        for entry in meaningful_entries[:limit]:
            if self._process_entry(entry):
                processed_count += 1
        
        if processed_count > 0:
            self.knowledge.rebuild_index()
            
        return processed_count

    def _process_entry(self, entry: LedgerEntry) -> bool:
        """Process a single entry for evolution."""
        # 1. Semantic Deduplication with Hard Action Match
        query = f"{entry.action} {' '.join(str(v) for v in entry.metadata.values())}"
        hits = self.knowledge.search(query, limit=5)
        
        # Level 1: Hard Match on Action + Level 2: High Confidence Score
        target_hit = None
        action_title = entry.action.replace("_", " ").title()
        for hit in hits:
            # Check if action name is in heading (normalized)
            if action_title in hit.chunk.heading and hit.score > self.min_score:
                target_hit = hit
                break
        
        if target_hit:
            # Merge into existing runbook
            return self._merge_into_runbook(target_hit, entry)
        else:
            # Create new runbook
            return self._create_new_runbook(entry)

    def _create_new_runbook(self, entry: LedgerEntry) -> bool:
        """Generate and save a new Runbook."""
        steps_raw = entry.checkpoint.get("steps", [])
        steps_formatted = "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps_raw))
        
        summary = entry.metadata.get("summary") or f"Successfully executed {entry.action}."
        
        runbook_content = RUNBOOK_TEMPLATE.format(
            action=entry.action.replace("_", " ").title(),
            description=f"Automated runbook generated from successful execution of {entry.action}.",
            entry_id=entry.id,
            priority_score=0.5,
            generated_at=entry.updated_at,
            context=json.dumps(entry.metadata, indent=2),
            steps=steps_formatted,
            verification="Verify that the target system state matches the desired outcome defined in the steps.",
            summary=summary
        )
        
        filename = f"{entry.action}_{entry.id[:8]}.md"
        file_path = self.evolved_dir / filename
        file_path.write_text(runbook_content, encoding="utf-8")
        
        logger.info(f"Created new Runbook: {file_path}")
        return True

    def _merge_into_runbook(self, hit: SearchHit, entry: LedgerEntry) -> bool:
        """Merge a new case into an existing Runbook."""
        file_path = Path(hit.chunk.source_path)
        if not file_path.exists():
            return False
            
        content = file_path.read_text(encoding="utf-8")
        
        # Check if entry already exists in case studies
        if entry.id in content:
            return False
            
        summary = entry.metadata.get("summary") or f"Another successful instance of {entry.action}."
        new_case = CASE_STUDY_TEMPLATE.format(
            entry_id=entry.id,
            summary=summary,
            updated_at=entry.updated_at
        )
        
        # Append to Case Studies section or at the end
        if "## Case Studies" in content:
            updated_content = content.replace("## Case Studies", f"## Case Studies{new_case}")
        else:
            updated_content = content + f"\n## Case Studies\n{new_case}"
            
        file_path.write_text(updated_content, encoding="utf-8")
        logger.info(f"Merged Case {entry.id} into Runbook: {file_path}")
        return True
