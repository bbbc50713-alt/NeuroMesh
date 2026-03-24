"""
Skill 加载器 - 渐进式加载和管理 Skills

渐进式加载流程:
1. 启动时只加载 Skills 元数据（名称、描述）
2. 工具调用时检查是否已加载
3. 如果未加载，动态加载 Skill
4. 支持卸载不常用的 Skills

功能:
1. 加载 Skill 的 MCP 配置
2. 加载 Skill 的脚本
3. 将 Skill 转换为可调用的工具
4. 渐进式加载（按需加载）
"""

import asyncio
import json
import os
import sys
import time
import importlib.util
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


class SkillLoadState(Enum):
    """Skill 加载状态"""
    METADATA_ONLY = "metadata_only"  # 只加载了元数据
    FULLY_LOADED = "fully_loaded"    # 完全加载
    ERROR = "error"                  # 加载错误


@dataclass
class SkillMetadata:
    """Skill 元数据（轻量级）"""
    name: str
    path: str
    description: str = ""
    enabled: bool = True
    has_script: bool = False
    has_mcp: bool = False
    tool_count: int = 0
    load_state: SkillLoadState = SkillLoadState.METADATA_ONLY
    last_used: float = 0
    load_time: float = 0


@dataclass
class SkillTool:
    """Skill 工具"""
    name: str
    description: str
    skill_name: str
    skill_path: str
    tool_type: str  # "mcp" 或 "script"
    handler: Optional[Callable] = None
    mcp_config: Optional[Dict] = None
    input_schema: Dict = None
    
    def __post_init__(self):
        if self.input_schema is None:
            self.input_schema = {"type": "object", "properties": {}}


class SkillLoader:
    """Skill 加载器 - 支持渐进式加载"""
    
    def __init__(self, max_loaded_skills: int = 20, auto_unload: bool = True):
        self.max_loaded_skills = max_loaded_skills
        self.auto_unload = auto_unload
        
        # 元数据（轻量级，始终加载）
        self.skills_metadata: Dict[str, SkillMetadata] = {}
        
        # 完全加载的工具（按需加载）
        self.loaded_tools: Dict[str, SkillTool] = {}
        
        # 脚本模块
        self.script_modules: Dict[str, Any] = {}
        
        # 加载锁（防止并发加载同一个 Skill）
        self._loading_locks: Dict[str, bool] = {}
    
    def register_skill(self, skill_path: str) -> Optional[SkillMetadata]:
        """注册 Skill（只加载元数据）"""
        if not os.path.isdir(skill_path):
            return None
        
        skill_name = os.path.basename(skill_path)
        
        # 检查是否已注册
        if skill_name in self.skills_metadata:
            return self.skills_metadata[skill_name]
        
        skill_md = os.path.join(skill_path, "skill.md")
        script_dir = os.path.join(skill_path, "script")
        mcp_dir = os.path.join(skill_path, "mcp")
        
        # 读取描述
        description = ""
        if os.path.exists(skill_md):
            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")
                    for line in lines[:5]:
                        if line.startswith("# "):
                            description = line[2:].strip()
                            break
            except:
                pass
        
        # 检查结构
        has_script = os.path.isdir(script_dir)
        has_mcp = os.path.isdir(mcp_dir)
        
        # 预估工具数量
        tool_count = 0
        if has_script:
            for f in os.listdir(script_dir):
                if f.endswith(".py"):
                    tool_count += 5  # 预估每个脚本有5个工具
        if has_mcp:
            mcp_config_path = os.path.join(mcp_dir, "mcp.json")
            if os.path.exists(mcp_config_path):
                try:
                    with open(mcp_config_path, "r", encoding="utf-8") as f:
                        mcp_config = json.load(f)
                        tool_count += len(mcp_config.get("mcpServers", {}))
                except:
                    pass
        
        metadata = SkillMetadata(
            name=skill_name,
            path=skill_path,
            description=description,
            has_script=has_script,
            has_mcp=has_mcp,
            tool_count=tool_count,
            load_state=SkillLoadState.METADATA_ONLY
        )
        
        self.skills_metadata[skill_name] = metadata
        return metadata
    
    def register_skills_from_config(self, skills_config: Dict[str, Any]) -> int:
        """从配置注册多个 Skills"""
        count = 0
        for skill_name, skill_data in skills_config.items():
            skill_path = skill_data.get("path", "")
            if skill_path and os.path.isdir(skill_path):
                metadata = self.register_skill(skill_path)
                if metadata:
                    count += 1
        return count
    
    async def load_skill_full(self, skill_name: str) -> List[SkillTool]:
        """完全加载 Skill（按需调用）"""
        
        # 检查是否已注册
        if skill_name not in self.skills_metadata:
            return []
        
        metadata = self.skills_metadata[skill_name]
        
        # 检查是否已完全加载
        if metadata.load_state == SkillLoadState.FULLY_LOADED:
            return [t for t in self.loaded_tools.values() if t.skill_name == skill_name]
        
        # 检查是否正在加载
        if self._loading_locks.get(skill_name, False):
            # 等待加载完成
            for _ in range(50):  # 最多等待5秒
                await asyncio.sleep(0.1)
                if metadata.load_state == SkillLoadState.FULLY_LOADED:
                    return [t for t in self.loaded_tools.values() if t.skill_name == skill_name]
            return []
        
        self._loading_locks[skill_name] = True
        
        try:
            tools = []
            skill_path = metadata.path
            script_dir = os.path.join(skill_path, "script")
            mcp_dir = os.path.join(skill_path, "mcp")
            
            # 加载脚本
            if metadata.has_script and os.path.isdir(script_dir):
                for script_file in os.listdir(script_dir):
                    if script_file.endswith(".py"):
                        script_path = os.path.join(script_dir, script_file)
                        script_tools = self._load_script(skill_name, script_path)
                        tools.extend(script_tools)
            
            # 加载 MCP 配置
            if metadata.has_mcp and os.path.isdir(mcp_dir):
                mcp_config_path = os.path.join(mcp_dir, "mcp.json")
                if os.path.exists(mcp_config_path):
                    try:
                        with open(mcp_config_path, "r", encoding="utf-8") as f:
                            mcp_config = json.load(f)
                        
                        for server_name, server_config in mcp_config.get("mcpServers", {}).items():
                            tool = SkillTool(
                                name=f"skill_{skill_name}_{server_name}",
                                description=f"[Skill:{skill_name}] {server_config.get('description', metadata.description)}",
                                skill_name=skill_name,
                                skill_path=skill_path,
                                tool_type="mcp",
                                mcp_config=server_config
                            )
                            tools.append(tool)
                            self.loaded_tools[tool.name] = tool
                    except Exception as e:
                        print(f"❌ 加载 Skill MCP 失败: {skill_name} - {e}")
            
            # 更新状态
            metadata.load_state = SkillLoadState.FULLY_LOADED
            metadata.load_time = time.time()
            metadata.tool_count = len(tools)
            
            # 自动卸载不常用的 Skills
            if self.auto_unload:
                self._auto_unload_if_needed()
            
            print(f"✅ 渐进式加载 Skill: {skill_name} -> {len(tools)} 个工具")
            return tools
            
        except Exception as e:
            metadata.load_state = SkillLoadState.ERROR
            print(f"❌ 加载 Skill 失败: {skill_name} - {e}")
            return []
        finally:
            self._loading_locks[skill_name] = False
    
    def _load_script(self, skill_name: str, script_path: str) -> List[SkillTool]:
        """加载 Python 脚本"""
        tools = []
        
        try:
            module = self._load_script_module(skill_name, script_path)
            if module:
                for attr_name in dir(module):
                    if not attr_name.startswith("_"):
                        attr = getattr(module, attr_name)
                        if callable(attr):
                            tool = SkillTool(
                                name=f"skill_{skill_name}_{attr_name}",
                                description=f"[Skill:{skill_name}] {attr.__doc__ or attr_name}",
                                skill_name=skill_name,
                                skill_path=os.path.dirname(script_path),
                                tool_type="script",
                                handler=attr
                            )
                            tools.append(tool)
                            self.loaded_tools[tool.name] = tool
        except Exception as e:
            print(f"❌ 加载脚本失败: {script_path} - {e}")
        
        return tools
    
    def _load_script_module(self, skill_name: str, script_path: str) -> Optional[Any]:
        """加载 Python 脚本模块"""
        module_name = f"skill_{skill_name}_{os.path.basename(script_path)[:-3]}"
        
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self.script_modules[module_name] = module
            return module
        return None
    
    def _auto_unload_if_needed(self):
        """自动卸载不常用的 Skills"""
        loaded_count = len([m for m in self.skills_metadata.values() 
                           if m.load_state == SkillLoadState.FULLY_LOADED])
        
        if loaded_count > self.max_loaded_skills:
            # 找到最久未使用的 Skills
            loaded_skills = [(name, meta) for name, meta in self.skills_metadata.items()
                            if meta.load_state == SkillLoadState.FULLY_LOADED]
            
            # 按最后使用时间排序
            loaded_skills.sort(key=lambda x: x[1].last_used)
            
            # 卸载最久未使用的
            to_unload = loaded_skills[:loaded_count - self.max_loaded_skills]
            for skill_name, _ in to_unload:
                self.unload_skill(skill_name)
    
    def unload_skill(self, skill_name: str):
        """卸载 Skill"""
        if skill_name not in self.skills_metadata:
            return
        
        metadata = self.skills_metadata[skill_name]
        
        # 移除工具
        tools_to_remove = [name for name, tool in self.loaded_tools.items() 
                          if tool.skill_name == skill_name]
        for name in tools_to_remove:
            del self.loaded_tools[name]
        
        # 卸载脚本模块
        modules_to_remove = [name for name in self.script_modules 
                            if name.startswith(f"skill_{skill_name}_")]
        for name in modules_to_remove:
            if name in sys.modules:
                del sys.modules[name]
            del self.script_modules[name]
        
        # 更新状态
        metadata.load_state = SkillLoadState.METADATA_ONLY
        print(f"🔄 卸载 Skill: {skill_name}")
    
    def get_tool(self, tool_name: str) -> Optional[SkillTool]:
        """获取工具"""
        return self.loaded_tools.get(tool_name)
    
    def get_skill_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """获取 Skill 元数据"""
        return self.skills_metadata.get(skill_name)
    
    def get_all_metadata(self) -> Dict[str, SkillMetadata]:
        """获取所有 Skill 元数据"""
        return self.skills_metadata
    
    def get_loaded_tools(self) -> List[SkillTool]:
        """获取所有已加载的工具"""
        return list(self.loaded_tools.values())
    
    def get_tool_definitions(self) -> List[Dict]:
        """获取工具定义（用于 LLM function calling）"""
        definitions = []
        
        # 已加载的工具
        for tool in self.loaded_tools.values():
            definitions.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema
                }
            })
        
        # 未加载的 Skills（提供元数据）
        for skill_name, metadata in self.skills_metadata.items():
            if metadata.load_state != SkillLoadState.FULLY_LOADED:
                # 提供一个占位工具，让 LLM 知道可以加载这个 Skill
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": f"skill_{skill_name}_load",
                        "description": f"[未加载] {metadata.description} (工具数: {metadata.tool_count})",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "_load_skill": {"type": "boolean", "description": "设置为 true 以加载此 Skill"}
                            }
                        }
                    }
                })
        
        return definitions
    
    async def ensure_tool_loaded(self, tool_name: str) -> Optional[SkillTool]:
        """确保工具已加载（渐进式加载核心方法）"""
        
        # 检查是否已加载
        if tool_name in self.loaded_tools:
            tool = self.loaded_tools[tool_name]
            # 更新最后使用时间
            if tool.skill_name in self.skills_metadata:
                self.skills_metadata[tool.skill_name].last_used = time.time()
            return tool
        
        # 检查是否是加载占位工具
        if tool_name.endswith("_load"):
            skill_name = tool_name.replace("skill_", "").replace("_load", "")
            await self.load_skill_full(skill_name)
            return None
        
        # 尝试从工具名推断 Skill 名称并加载
        # 工具名格式: skill_{skill_name}_{tool_function}
        # 需要找到匹配的 skill_name
        if tool_name.startswith("skill_"):
            remaining = tool_name[6:]  # 移除 "skill_" 前缀
            
            # 尝试匹配已注册的 skills
            for skill_name in self.skills_metadata.keys():
                if remaining.startswith(f"{skill_name}_"):
                    await self.load_skill_full(skill_name)
                    if tool_name in self.loaded_tools:
                        return self.loaded_tools[tool_name]
        
        return None
    
    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """调用工具（自动加载）"""
        
        # 确保工具已加载
        tool = await self.ensure_tool_loaded(tool_name)
        
        if not tool:
            return {"error": f"工具不存在或无法加载: {tool_name}"}
        
        # 更新最后使用时间
        if tool.skill_name in self.skills_metadata:
            self.skills_metadata[tool.skill_name].last_used = time.time()
        
        if tool.tool_type == "script" and tool.handler:
            try:
                if asyncio.iscoroutinefunction(tool.handler):
                    result = await tool.handler(**arguments)
                else:
                    result = tool.handler(**arguments)
                return {"success": True, "result": result}
            except Exception as e:
                return {"error": str(e)}
        
        elif tool.tool_type == "mcp":
            return {"error": "MCP 类型的 Skill 需要通过 MCPClientManager 调用", "mcp_config": tool.mcp_config}
        
        return {"error": f"无法调用工具: {tool_name}"}
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        loaded_count = len([m for m in self.skills_metadata.values() 
                          if m.load_state == SkillLoadState.FULLY_LOADED])
        
        return {
            "total_skills": len(self.skills_metadata),
            "loaded_skills": loaded_count,
            "total_tools": len(self.loaded_tools),
            "max_loaded": self.max_loaded_skills,
            "auto_unload": self.auto_unload
        }
