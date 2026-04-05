from __future__ import annotations

import logging
import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("OpsSentry.SkillLoader")

@dataclass(slots=True)
class SkillMeta:
    name: str
    version: str
    description: str
    trigger: List[str]
    path: Path
    is_private: bool = False  # True: agent-private, False: account-level

class SkillLoader:
    """
    运维技能加载器。
    扫描 skills/ 目录，解析 SKILL.md frontmatter，并为 System Prompt 提供注入文本。
    """

    def __init__(self, accio_home: Path) -> None:
        self.accio_home = accio_home

    def scan_skills(self, uid: str, did: str) -> Dict[str, SkillMeta]:
        """
        扫描账户级和 Agent 私有级技能。
        优先级：Agent 私有 (did/agent-core/skills/) > 账户级 (uid/skills/)
        """
        all_skills: Dict[str, SkillMeta] = {}

        # 1. 扫描账户级共享技能 (uid/skills/)
        account_skills_dir = self.accio_home / "accounts" / uid / "skills"
        if account_skills_dir.is_dir():
            for skill_dir in account_skills_dir.iterdir():
                if skill_dir.is_dir():
                    meta = self._load_skill_meta(skill_dir, is_private=False)
                    if meta:
                        all_skills[meta.name] = meta

        # 2. 扫描 Agent 私有技能 (did/agent-core/skills/)
        # DID path is nested under accounts/<uid>/agents/<did>
        agent_skills_dir = self.accio_home / "accounts" / uid / "agents" / did / "agent-core" / "skills"
        if agent_skills_dir.is_dir():
            for skill_dir in agent_skills_dir.iterdir():
                if skill_dir.is_dir():
                    meta = self._load_skill_meta(skill_dir, is_private=True)
                    if meta:
                        # Agent-private overrides account-level
                        all_skills[meta.name] = meta

        return all_skills

    def get_system_prompt_injection(self, uid: str, did: str, enabled_skills: List[str]) -> str:
        """
        根据已启用的技能列表，获取用于注入 System Prompt 的 Markdown 文本。
        """
        available_skills = self.scan_skills(uid, did)
        injection_parts = []

        for skill_name in enabled_skills:
            if skill_name in available_skills:
                meta = available_skills[skill_name]
                skill_text = self._load_skill_content(meta.path)
                if skill_text:
                    injection_parts.append(f"### Skill: {meta.name} ({meta.version})\n{skill_text}")

        if not injection_parts:
            return "No specialized skills currently enabled."

        return "\n\n".join(injection_parts)

    def _load_skill_meta(self, skill_dir: Path, is_private: bool) -> Optional[SkillMeta]:
        """从 SKILL.md 解析 frontmatter"""
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            return None

        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 解析 YAML frontmatter (--- ... ---)
            if not content.startswith("---"):
                return None

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            frontmatter_raw = parts[1]
            data = yaml.safe_load(frontmatter_raw)

            if not isinstance(data, dict):
                return None

            return SkillMeta(
                name=data.get("name", skill_dir.name),
                version=data.get("version", "v0.1"),
                description=data.get("description", ""),
                trigger=data.get("trigger", []),
                path=skill_file,
                is_private=is_private
            )
        except Exception as e:
            logger.error(f"Failed to load skill meta from {skill_file}: {e}")
            return None

    def _load_skill_content(self, skill_file: Path) -> Optional[str]:
        """获取技能正文（除去 frontmatter）"""
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
        except Exception as e:
            logger.error(f"Failed to load skill content from {skill_file}: {e}")
            return None
