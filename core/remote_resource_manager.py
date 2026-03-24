"""
远程资源管理器 - 管理链上节点的 Skills 和 MCP

功能:
1. 发现链上节点的 Skills 和 MCP
2. 远程 Skills 渐进式加载
3. 远程 MCP 直接调用
4. 本地资源广播

通信协议:
- SKILL_ANNOUNCE: 广播本地 Skills 元数据
- SKILL_METADATA_REQUEST/RESPONSE: 请求/响应 Skills 元数据
- SKILL_LOAD_REQUEST/RESPONSE: 请求/响应加载 Skill
- SKILL_TOOL_CALL/RESPONSE: 调用远程 Skill 工具
- REMOTE_MCP_ANNOUNCE: 广播本地 MCP
- REMOTE_MCP_CALL/RESPONSE: 调用远程 MCP
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from network.p2p_network import MessageType


class RemoteResourceType(Enum):
    SKILL = "skill"
    MCP = "mcp"


@dataclass
class RemoteSkillMetadata:
    """远程 Skill 元数据"""
    skill_name: str
    node_id: str
    description: str = ""
    tool_count: int = 0
    has_script: bool = False
    has_mcp: bool = False
    last_seen: float = 0
    
    def to_dict(self) -> Dict:
        return {
            "skill_name": self.skill_name,
            "node_id": self.node_id,
            "description": self.description,
            "tool_count": self.tool_count,
            "has_script": self.has_script,
            "has_mcp": self.has_mcp,
            "last_seen": self.last_seen
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "RemoteSkillMetadata":
        return cls(
            skill_name=data.get("skill_name", ""),
            node_id=data.get("node_id", ""),
            description=data.get("description", ""),
            tool_count=data.get("tool_count", 0),
            has_script=data.get("has_script", False),
            has_mcp=data.get("has_mcp", False),
            last_seen=data.get("last_seen", time.time())
        )


@dataclass
class RemoteMCPMetadata:
    """远程 MCP 元数据"""
    mcp_name: str
    node_id: str
    tools: List[Dict] = field(default_factory=list)
    description: str = ""
    last_seen: float = 0
    
    def to_dict(self) -> Dict:
        return {
            "mcp_name": self.mcp_name,
            "node_id": self.node_id,
            "tools": self.tools,
            "description": self.description,
            "last_seen": self.last_seen
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "RemoteMCPMetadata":
        return cls(
            mcp_name=data.get("mcp_name", ""),
            node_id=data.get("node_id", ""),
            tools=data.get("tools", []),
            description=data.get("description", ""),
            last_seen=data.get("last_seen", time.time())
        )


@dataclass
class RemoteTool:
    """远程工具"""
    name: str
    node_id: str
    resource_type: RemoteResourceType
    resource_name: str
    description: str = ""
    input_schema: Dict = None
    
    def __post_init__(self):
        if self.input_schema is None:
            self.input_schema = {"type": "object", "properties": {}}
    
    def to_tool_definition(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[远程:{self.node_id}] {self.description}",
                "parameters": self.input_schema
            }
        }


class RemoteResourceManager:
    """
    远程资源管理器
    
    管理:
    1. 远程 Skills 注册表
    2. 远程 MCP 注册表
    3. 远程工具调用
    4. 本地资源广播
    """
    
    def __init__(self, node_id: str, p2p_network, skill_loader=None, mcp_manager=None):
        self.node_id = node_id
        self.p2p = p2p_network
        self.skill_loader = skill_loader
        self.mcp_manager = mcp_manager
        
        self.remote_skills: Dict[str, RemoteSkillMetadata] = {}
        self.remote_mcps: Dict[str, RemoteMCPMetadata] = {}
        self.remote_tools: Dict[str, RemoteTool] = {}
        
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._request_timeout = 30.0
        
        self._register_handlers()
    
    def _register_handlers(self):
        self.p2p.on_message(MessageType.SKILL_ANNOUNCE.value, self._handle_skill_announce)
        self.p2p.on_message(MessageType.SKILL_METADATA_RESPONSE.value, self._handle_skill_metadata_response)
        self.p2p.on_message(MessageType.SKILL_LOAD_RESPONSE.value, self._handle_skill_load_response)
        self.p2p.on_message(MessageType.SKILL_TOOL_RESPONSE.value, self._handle_skill_tool_response)
        self.p2p.on_message(MessageType.REMOTE_MCP_ANNOUNCE.value, self._handle_mcp_announce)
        self.p2p.on_message(MessageType.REMOTE_MCP_RESPONSE.value, self._handle_mcp_response)
        
        self.p2p.on_message(MessageType.SKILL_METADATA_REQUEST.value, self._handle_skill_metadata_request)
        self.p2p.on_message(MessageType.SKILL_LOAD_REQUEST.value, self._handle_skill_load_request)
        self.p2p.on_message(MessageType.SKILL_TOOL_CALL.value, self._handle_skill_tool_call)
        self.p2p.on_message(MessageType.REMOTE_MCP_CALL.value, self._handle_mcp_call)
    
    async def broadcast_local_skills(self):
        if not self.skill_loader:
            return
        
        skills_metadata = self.skill_loader.get_all_metadata()
        for skill_name, metadata in skills_metadata.items():
            message = {
                "type": MessageType.SKILL_ANNOUNCE.value,
                "node_id": self.node_id,
                "skill": {
                    "skill_name": skill_name,
                    "description": metadata.description,
                    "tool_count": metadata.tool_count,
                    "has_script": metadata.has_script,
                    "has_mcp": metadata.has_mcp
                },
                "timestamp": time.time()
            }
            await self.p2p._publish(self.p2p.topic_crdt, message)
    
    async def broadcast_local_mcps(self):
        if not self.mcp_manager:
            return
        
        for mcp_name, client in self.mcp_manager.clients.items():
            tools = client.get_tool_definitions() if hasattr(client, 'get_tool_definitions') else []
            message = {
                "type": MessageType.REMOTE_MCP_ANNOUNCE.value,
                "node_id": self.node_id,
                "mcp": {
                    "mcp_name": mcp_name,
                    "tools": tools,
                    "description": f"MCP Server: {mcp_name}"
                },
                "timestamp": time.time()
            }
            await self.p2p._publish(self.p2p.topic_crdt, message)
    
    async def _handle_skill_announce(self, message: Dict):
        sender = message.get("node_id")
        if sender == self.node_id:
            return
        
        skill_data = message.get("skill", {})
        skill_name = skill_data.get("skill_name", "")
        
        if not skill_name:
            return
        
        remote_skill = RemoteSkillMetadata(
            skill_name=skill_name,
            node_id=sender,
            description=skill_data.get("description", ""),
            tool_count=skill_data.get("tool_count", 0),
            has_script=skill_data.get("has_script", False),
            has_mcp=skill_data.get("has_mcp", False),
            last_seen=time.time()
        )
        
        key = f"{sender}:{skill_name}"
        self.remote_skills[key] = remote_skill
        
        for i in range(remote_skill.tool_count):
            tool_name = f"remote_{sender}_{skill_name}_tool_{i}"
            self.remote_tools[tool_name] = RemoteTool(
                name=tool_name,
                node_id=sender,
                resource_type=RemoteResourceType.SKILL,
                resource_name=skill_name,
                description=f"[远程Skill] {skill_name} - 工具 {i+1}"
            )
        
        print(f"📡 发现远程 Skill: {skill_name}@{sender} ({remote_skill.tool_count} 个工具)")
    
    async def _handle_mcp_announce(self, message: Dict):
        sender = message.get("node_id")
        if sender == self.node_id:
            return
        
        mcp_data = message.get("mcp", {})
        mcp_name = mcp_data.get("mcp_name", "")
        
        if not mcp_name:
            return
        
        remote_mcp = RemoteMCPMetadata(
            mcp_name=mcp_name,
            node_id=sender,
            tools=mcp_data.get("tools", []),
            description=mcp_data.get("description", ""),
            last_seen=time.time()
        )
        
        key = f"{sender}:{mcp_name}"
        self.remote_mcps[key] = remote_mcp
        
        for tool_def in remote_mcp.tools:
            tool_info = tool_def.get("function", {})
            original_name = tool_info.get("name", "")
            if original_name:
                remote_tool_name = f"remote_{sender}_{original_name}"
                self.remote_tools[remote_tool_name] = RemoteTool(
                    name=remote_tool_name,
                    node_id=sender,
                    resource_type=RemoteResourceType.MCP,
                    resource_name=mcp_name,
                    description=tool_info.get("description", ""),
                    input_schema=tool_info.get("parameters", {})
                )
        
        print(f"📡 发现远程 MCP: {mcp_name}@{sender} ({len(remote_mcp.tools)} 个工具)")
    
    async def request_skill_metadata(self, target_node: str, skill_name: str) -> Optional[Dict]:
        request_id = f"req_{time.time_ns()}"
        
        future = asyncio.Future()
        self._pending_requests[request_id] = future
        
        message = {
            "type": MessageType.SKILL_METADATA_REQUEST.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "skill_name": skill_name,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, message)
        
        try:
            result = await asyncio.wait_for(future, timeout=self._request_timeout)
            return result
        except asyncio.TimeoutError:
            del self._pending_requests[request_id]
            return None
    
    async def request_skill_load(self, target_node: str, skill_name: str) -> Optional[Dict]:
        request_id = f"req_{time.time_ns()}"
        
        future = asyncio.Future()
        self._pending_requests[request_id] = future
        
        message = {
            "type": MessageType.SKILL_LOAD_REQUEST.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "skill_name": skill_name,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, message)
        
        try:
            result = await asyncio.wait_for(future, timeout=self._request_timeout)
            return result
        except asyncio.TimeoutError:
            del self._pending_requests[request_id]
            return None
    
    async def call_remote_skill_tool(self, target_node: str, skill_name: str, 
                                      tool_name: str, arguments: Dict) -> Dict:
        """
        调用远程 Skill 工具（使用点对点直连）
        """
        payload = {
            "skill_name": skill_name,
            "tool_name": tool_name,
            "arguments": arguments
        }
        
        result = await self.p2p.direct_call(
            target_node=target_node,
            call_type="skill_tool",
            payload=payload,
            timeout=self._request_timeout
        )
        
        return result
    
    async def call_remote_mcp_tool(self, target_node: str, mcp_name: str,
                                    tool_name: str, arguments: Dict) -> Dict:
        """
        调用远程 MCP 工具（使用点对点直连）
        """
        payload = {
            "mcp_name": mcp_name,
            "tool_name": tool_name,
            "arguments": arguments
        }
        
        result = await self.p2p.direct_call(
            target_node=target_node,
            call_type="mcp_tool",
            payload=payload,
            timeout=self._request_timeout
        )
        
        return result
    
    async def delegate_task_to_remote(self, task_id: str, task_data: Dict,
                                       required_capabilities: List[str] = None,
                                       preferred_node: str = None) -> Dict:
        """
        委派任务到远程节点
        
        Args:
            task_id: 任务ID
            task_data: 任务数据
            required_capabilities: 所需能力
            preferred_node: 首选节点（如果指定则直接调用）
        
        Returns:
            任务执行结果
        """
        if preferred_node:
            payload = {
                "task_id": task_id,
                "task_data": task_data,
                "required_capabilities": required_capabilities or []
            }
            return await self.p2p.direct_call(
                target_node=preferred_node,
                call_type="task_execute",
                payload=payload,
                timeout=self._request_timeout * 2
            )
        else:
            return await self.p2p.delegate_task(
                task_id=task_id,
                task_data=task_data,
                required_capabilities=required_capabilities,
                timeout=self._request_timeout * 2
            )
    
    async def _handle_skill_metadata_request(self, message: Dict):
        if not self.skill_loader:
            return
        
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        
        metadata = self.skill_loader.get_skill_metadata(skill_name)
        
        response = {
            "type": MessageType.SKILL_METADATA_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "skill_name": skill_name,
            "metadata": metadata.__dict__ if metadata else None,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
    
    async def _handle_skill_metadata_response(self, message: Dict):
        request_id = message.get("request_id")
        
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            future.set_result(message.get("metadata"))
    
    async def _handle_skill_load_request(self, message: Dict):
        if not self.skill_loader:
            return
        
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        
        tools = await self.skill_loader.load_skill_full(skill_name)
        
        tool_definitions = []
        for tool in tools:
            tool_definitions.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema
            })
        
        response = {
            "type": MessageType.SKILL_LOAD_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "skill_name": skill_name,
            "tools": tool_definitions,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
    
    async def _handle_skill_load_response(self, message: Dict):
        request_id = message.get("request_id")
        
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            future.set_result(message.get("tools", []))
    
    async def _handle_skill_tool_call(self, message: Dict):
        if not self.skill_loader:
            return
        
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        
        result = await self.skill_loader.call_tool(tool_name, arguments)
        
        response = {
            "type": MessageType.SKILL_TOOL_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "result": result,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
    
    async def _handle_skill_tool_response(self, message: Dict):
        request_id = message.get("request_id")
        
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            future.set_result(message.get("result", {}))
    
    async def _handle_mcp_call(self, message: Dict):
        if not self.mcp_manager:
            return
        
        sender = message.get("node_id")
        request_id = message.get("request_id")
        mcp_name = message.get("mcp_name")
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        
        result = await self.mcp_manager.call_tool(tool_name, arguments)
        
        response = {
            "type": MessageType.REMOTE_MCP_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "result": result,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
    
    async def _handle_mcp_response(self, message: Dict):
        request_id = message.get("request_id")
        
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            future.set_result(message.get("result", {}))
    
    def get_remote_skills(self) -> Dict[str, RemoteSkillMetadata]:
        return self.remote_skills
    
    def get_remote_mcps(self) -> Dict[str, RemoteMCPMetadata]:
        return self.remote_mcps
    
    def get_remote_tools(self) -> List[Dict]:
        tools = []
        for tool in self.remote_tools.values():
            tools.append(tool.to_tool_definition())
        return tools
    
    def get_all_tools(self) -> List[Dict]:
        return self.get_remote_tools()
    
    def find_remote_tool(self, tool_name: str) -> Optional[RemoteTool]:
        return self.remote_tools.get(tool_name)
    
    def get_stats(self) -> Dict:
        return {
            "remote_skills": len(self.remote_skills),
            "remote_mcps": len(self.remote_mcps),
            "remote_tools": len(self.remote_tools),
            "pending_requests": len(self._pending_requests)
        }
