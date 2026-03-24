"""
Skills 管理模块 - 管理 Skills 配置

功能:
1. 添加 Skill
2. 删除 Skill
3. 列出 Skills
4. 发现可用 Skills
5. 挂载到节点

Skill 结构:
skill_name/
├── skill.md          # 必需 - Skill 描述和使用说明
├── script/           # 可选 - 脚本文件
│   └── *.py
└── mcp/              # 可选 - MCP 配置
    └── mcp.json
"""

import json
import os
import shutil
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from pathlib import Path


SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
SKILLS_CONFIG_PATH = os.path.join(SKILLS_DIR, "skills.json")


@dataclass
class SkillConfig:
    """Skill 配置"""
    name: str
    path: str
    description: str = ""
    enabled: bool = True
    has_script: bool = False
    has_mcp: bool = False
    mounted_to: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "enabled": self.enabled,
            "has_script": self.has_script,
            "has_mcp": self.has_mcp,
            "mounted_to": self.mounted_to
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SkillConfig":
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            has_script=data.get("has_script", False),
            has_mcp=data.get("has_mcp", False),
            mounted_to=data.get("mounted_to", [])
        )


class SkillManager:
    """Skill 管理器"""
    
    def __init__(self, skills_dir: str = SKILLS_DIR, config_path: str = SKILLS_CONFIG_PATH):
        self.skills_dir = skills_dir
        self.config_path = config_path
        self._ensure_dirs_exist()
    
    def _ensure_dirs_exist(self):
        """确保目录和配置文件存在"""
        os.makedirs(self.skills_dir, exist_ok=True)
        if not os.path.exists(self.config_path):
            self._save_config({"skills": {}, "mounted": {}})
    
    def _load_config(self) -> Dict:
        """加载配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"skills": {}, "mounted": {}}
    
    def _save_config(self, config: Dict):
        """保存配置"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def _validate_skill(self, skill_path: str) -> tuple:
        """验证 Skill 目录结构"""
        skill_md = os.path.join(skill_path, "skill.md")
        script_dir = os.path.join(skill_path, "script")
        mcp_dir = os.path.join(skill_path, "mcp")
        
        has_skill_md = os.path.exists(skill_md)
        has_script = os.path.isdir(script_dir)
        has_mcp = os.path.isdir(mcp_dir)
        
        return has_skill_md, has_script, has_mcp
    
    def _read_skill_description(self, skill_path: str) -> str:
        """读取 Skill 描述"""
        skill_md = os.path.join(skill_path, "skill.md")
        if os.path.exists(skill_md):
            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")
                    for line in lines[:10]:
                        if line.startswith("# "):
                            return line[2:].strip()
                    return content[:100] + "..." if len(content) > 100 else content
            except:
                pass
        return ""
    
    def discover_skills_in_dir(self, directory: str) -> List[str]:
        """发现目录中的 Skills"""
        discovered = []
        if not os.path.isdir(directory):
            return discovered
        
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                has_skill_md, _, _ = self._validate_skill(item_path)
                if has_skill_md:
                    discovered.append(item_path)
        
        return discovered
    
    def discover_local_skills(self) -> List[str]:
        """发现本地 Skills 目录中的 Skills"""
        return self.discover_skills_in_dir(self.skills_dir)
    
    def list_skills(self) -> Dict[str, SkillConfig]:
        """列出所有已配置的 Skills"""
        config = self._load_config()
        skills = {}
        for name, skill_data in config.get("skills", {}).items():
            skills[name] = SkillConfig.from_dict(skill_data)
        return skills
    
    def get_skill(self, name: str) -> Optional[SkillConfig]:
        """获取单个 Skill"""
        skills = self.list_skills()
        return skills.get(name)
    
    def add_skill(self, skill_path: str, copy_to_local: bool = False) -> Optional[str]:
        """添加 Skill"""
        if not os.path.isdir(skill_path):
            return None
        
        has_skill_md, has_script, has_mcp = self._validate_skill(skill_path)
        if not has_skill_md:
            return None
        
        skill_name = os.path.basename(skill_path)
        
        if copy_to_local:
            local_path = os.path.join(self.skills_dir, skill_name)
            if os.path.exists(local_path):
                return None
            shutil.copytree(skill_path, local_path)
            skill_path = local_path
        
        description = self._read_skill_description(skill_path)
        
        config = SkillConfig(
            name=skill_name,
            path=skill_path,
            description=description,
            has_script=has_script,
            has_mcp=has_mcp
        )
        
        full_config = self._load_config()
        if "skills" not in full_config:
            full_config["skills"] = {}
        
        full_config["skills"][skill_name] = config.to_dict()
        self._save_config(full_config)
        
        return skill_name
    
    def create_skill(self, name: str, description: str = "", 
                     with_script: bool = False, with_mcp: bool = False) -> bool:
        """创建新 Skill"""
        skill_path = os.path.join(self.skills_dir, name)
        if os.path.exists(skill_path):
            return False
        
        os.makedirs(skill_path, exist_ok=True)
        
        skill_md_content = f"# {name}\n\n{description}\n\n## 使用说明\n\n"
        with open(os.path.join(skill_path, "skill.md"), "w", encoding="utf-8") as f:
            f.write(skill_md_content)
        
        if with_script:
            script_dir = os.path.join(skill_path, "script")
            os.makedirs(script_dir, exist_ok=True)
            with open(os.path.join(script_dir, "main.py"), "w", encoding="utf-8") as f:
                f.write(f'"""{name} - 主脚本"""\n\ndef run():\n    pass\n\nif __name__ == "__main__":\n    run()\n')
        
        if with_mcp:
            mcp_dir = os.path.join(skill_path, "mcp")
            os.makedirs(mcp_dir, exist_ok=True)
            with open(os.path.join(mcp_dir, "mcp.json"), "w", encoding="utf-8") as f:
                json.dump({"mcpServers": {}}, f, indent=2)
        
        return self.add_skill(skill_path) is not None
    
    def delete_skill(self, name: str, remove_files: bool = False) -> bool:
        """删除 Skill"""
        config = self._load_config()
        if name not in config.get("skills", {}):
            return False
        
        skill_config = SkillConfig.from_dict(config["skills"][name])
        
        del config["skills"][name]
        
        if name in config.get("mounted", {}):
            del config["mounted"][name]
        
        self._save_config(config)
        
        if remove_files and os.path.exists(skill_config.path):
            if skill_config.path.startswith(self.skills_dir):
                shutil.rmtree(skill_config.path)
        
        return True
    
    def enable_skill(self, name: str) -> bool:
        """启用 Skill"""
        skill = self.get_skill(name)
        if not skill:
            return False
        skill.enabled = True
        return self._update_skill_config(skill)
    
    def disable_skill(self, name: str) -> bool:
        """禁用 Skill"""
        skill = self.get_skill(name)
        if not skill:
            return False
        skill.enabled = False
        return self._update_skill_config(skill)
    
    def _update_skill_config(self, skill: SkillConfig) -> bool:
        """更新 Skill 配置"""
        config = self._load_config()
        if skill.name not in config.get("skills", {}):
            return False
        config["skills"][skill.name] = skill.to_dict()
        self._save_config(config)
        return True
    
    def mount_to_node(self, skill_name: str, node_name: str) -> bool:
        """将 Skill 挂载到节点"""
        skill = self.get_skill(skill_name)
        if not skill or not skill.enabled:
            return False
        
        if node_name not in skill.mounted_to:
            skill.mounted_to.append(node_name)
            return self._update_skill_config(skill)
        return True
    
    def unmount_from_node(self, skill_name: str, node_name: str) -> bool:
        """从节点卸载 Skill"""
        skill = self.get_skill(skill_name)
        if not skill:
            return False
        
        if node_name in skill.mounted_to:
            skill.mounted_to.remove(node_name)
            return self._update_skill_config(skill)
        return True
    
    def get_mounted_skills(self, node_name: str) -> List[SkillConfig]:
        """获取节点挂载的 Skills"""
        skills = self.list_skills()
        return [s for s in skills.values() if node_name in s.mounted_to and s.enabled]
    
    def get_skill_scripts(self, skill_name: str) -> List[str]:
        """获取 Skill 的脚本文件列表"""
        skill = self.get_skill(skill_name)
        if not skill or not skill.has_script:
            return []
        
        script_dir = os.path.join(skill.path, "script")
        if not os.path.isdir(script_dir):
            return []
        
        scripts = []
        for f in os.listdir(script_dir):
            if f.endswith(".py"):
                scripts.append(os.path.join(script_dir, f))
        return scripts
    
    def get_skill_mcp_config(self, skill_name: str) -> Optional[Dict]:
        """获取 Skill 的 MCP 配置"""
        skill = self.get_skill(skill_name)
        if not skill or not skill.has_mcp:
            return None
        
        mcp_config_path = os.path.join(skill.path, "mcp", "mcp.json")
        if not os.path.exists(mcp_config_path):
            return None
        
        try:
            with open(mcp_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return None
    
    def refresh_skill_info(self, skill_name: str) -> bool:
        """刷新 Skill 信息"""
        skill = self.get_skill(skill_name)
        if not skill:
            return False
        
        has_skill_md, has_script, has_mcp = self._validate_skill(skill.path)
        skill.has_script = has_script
        skill.has_mcp = has_mcp
        skill.description = self._read_skill_description(skill.path)
        
        return self._update_skill_config(skill)
