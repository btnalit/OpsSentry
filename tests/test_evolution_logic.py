import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.evolution_manager import EvolutionManager
from src.ops_ledger import LedgerEntry
from src.knowledge_core import SearchHit, KnowledgeChunk

class TestEvolutionDeduplication(unittest.TestCase):
    def setUp(self):
        self.mock_ledger = MagicMock()
        self.mock_knowledge = MagicMock()
        self.evolved_dir = Path("data/knowledge/test_evolved")
        self.evolved_dir.mkdir(parents=True, exist_ok=True)
        self.manager = EvolutionManager(self.mock_ledger, self.mock_knowledge, self.evolved_dir)

    def tearDown(self):
        if self.evolved_dir.exists():
            import shutil
            shutil.rmtree(self.evolved_dir)

    def test_low_score_creates_new_runbook(self):
        """验证分值较低时（低于修复后的阈值）应创建新 Runbook 而非合并"""
        entry = LedgerEntry(
            id="test-new",
            action="DISK_CLEANUP",
            status="completed",
            checkpoint={"steps": ["step 1", "step 2"]},
            created_at=1000,
            updated_at=2000,
            metadata={"summary": "New cleanup case"}
        )
        
        # 模拟 BM25 返回一个极低分（如 1.5），应被判定为“不相似”
        mock_chunk = MagicMock(spec=KnowledgeChunk)
        mock_chunk.heading = "Random Heading"
        mock_hit = MagicMock(spec=SearchHit)
        mock_hit.score = 1.5 
        mock_hit.chunk = mock_chunk
        self.mock_knowledge.search.return_value = [mock_hit]
        
        with patch.object(self.manager, '_create_new_runbook', return_value=True) as mock_create:
            with patch.object(self.manager, '_merge_into_runbook', return_value=True) as mock_merge:
                self.manager._process_entry(entry)
                
                # 如果修复成功，由于 1.5 远低于阈值，应调用 _create_new_runbook
                mock_create.assert_called_once()
                mock_merge.assert_not_called()

    def test_high_score_merges_runbook(self):
        """验证分值极高且 Action 匹配时应执行合并"""
        entry = LedgerEntry(
            id="test-merge",
            action="DISK_CLEANUP",
            status="completed",
            checkpoint={"steps": ["step 1", "step 2"]},
            created_at=1000,
            updated_at=2000,
            metadata={"summary": "Similar cleanup case"}
        )
        
        # 模拟 BM25 返回高分（如 25.0），且返回的 Chunk 包含相同的 Action
        mock_chunk = MagicMock(spec=KnowledgeChunk)
        mock_chunk.source_path = "evolved_cleanup.md"
        mock_chunk.heading = "Disk Cleanup Guide"
        
        mock_hit = MagicMock(spec=SearchHit)
        mock_hit.score = 25.0 
        mock_hit.chunk = mock_chunk
        self.mock_knowledge.search.return_value = [mock_hit]
        
        with patch.object(self.manager, '_create_new_runbook', return_value=True) as mock_create:
            with patch.object(self.manager, '_merge_into_runbook', return_value=True) as mock_merge:
                self.manager._process_entry(entry)
                
                # 应调用 _merge_into_runbook
                mock_merge.assert_called_once()
                mock_create.assert_not_called()

    def test_high_score_different_action_creates_new(self):
        """验证分值虽高但 Action 不匹配时，应创建新 Runbook 防止交叉污染"""
        entry = LedgerEntry(
            id="test-diff-action",
            action="MEM_RESTART",
            status="completed",
            checkpoint={"steps": ["restart service"]},
            created_at=1000,
            updated_at=2000,
            metadata={"summary": "Memory leak fix"}
        )
        
        # 模拟返回一个分数很高但内容关于 DISK_CLEANUP 的 Chunk
        mock_chunk = MagicMock(spec=KnowledgeChunk)
        mock_chunk.source_path = "evolved_cleanup.md"
        mock_chunk.heading = "Disk Cleanup Guide"
        
        mock_hit = MagicMock(spec=SearchHit)
        mock_hit.score = 30.0 
        mock_hit.chunk = mock_chunk
        self.mock_knowledge.search.return_value = [mock_hit]
        
        with patch.object(self.manager, '_create_new_runbook', return_value=True) as mock_create:
            with patch.object(self.manager, '_merge_into_runbook', return_value=True) as mock_merge:
                self.manager._process_entry(entry)
                
                # 由于 Action 不匹配（MEM_RESTART vs DISK_CLEANUP），不应合并，应创建新 Runbook
                mock_create.assert_called_once()
                mock_merge.assert_not_called()

if __name__ == "__main__":
    unittest.main()
