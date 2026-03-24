"""
MCP (Model Context Protocol) 协议实现

MCP是Anthropic提出的工具调用标准协议。
本模块实现MCP over libp2p，让Agent之间可以互相发现和调用工具。

核心概念:
1. MCPTool: 工具定义（名称、描述、参数schema）
2. MCPRegistry: 工具注册表
3. MCPRequest/MCPResponse: 请求响应结构
"""

import json
import time
import uuid
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum


class MCPMessageType(Enum):
    TOOL_REGISTER = "tool_register"
    TOOL_UNREGISTER = "tool_unregister"
    TOOL_DISCOVER = "tool_discover"
    TOOL_DISCOVER_RESPONSE = "tool_discover_response"
    TOOL_CALL = "tool_call"
    TOOL_CALL_RESPONSE = "tool_call_response"
    SKILL_BROADCAST = "skill_broadcast"


@dataclass
class MCPTool:
    """
    MCP工具定义
    
    遵循MCP标准:
    - name: 工具名称（唯一标识）
    - description: 工具描述（LLM可理解）
    - input_schema: JSON Schema格式的参数定义
    """
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    provider_node: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPTool":
        return cls(**data)


@dataclass
class MCPRequest:
    """
    MCP调用请求
    
    用于Agent A调用Agent B的工具
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    caller_node: str = ""
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPRequest":
        return cls(**data)


@dataclass 
class MCPResponse:
    """
    MCP调用响应
    
    标准化的工具执行结果
    """
    request_id: str = ""
    success: bool = False
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPResponse":
        return cls(**data)


ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


class MCPRegistry:
    """
    MCP工具注册表
    
    核心功能:
    1. 本地工具注册 - Agent注册自己提供的工具
    2. 远程工具发现 - 发现其他Agent提供的工具
    3. 工具调用路由 - 路由工具调用到正确的处理者
    """
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._local_tools: Dict[str, MCPTool] = {}
        self._handlers: Dict[str, ToolHandler] = {}
        self._remote_tools: Dict[str, Dict[str, MCPTool]] = {}
        self._pending_requests: Dict[str, MCPRequest] = {}
        self._request_callbacks: Dict[str, Any] = {}
    
    def register_tool(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        input_schema: Dict = None,
        tags: List[str] = None
    ) -> MCPTool:
        """
        注册本地工具
        
        Args:
            name: 工具名称
            description: 工具描述
            handler: 异步处理函数
            input_schema: 参数schema
            tags: 工具标签
        """
        tool = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            provider_node=self.node_id,
            tags=tags or []
        )
        
        self._local_tools[name] = tool
        self._handlers[name] = handler
        
        return tool
    
    def unregister_tool(self, name: str) -> bool:
        """注销本地工具"""
        if name in self._local_tools:
            del self._local_tools[name]
            del self._handlers[name]
            return True
        return False
    
    def get_local_tools(self) -> List[MCPTool]:
        """获取所有本地工具"""
        return list(self._local_tools.values())
    
    def get_all_tools(self) -> List[MCPTool]:
        """获取所有可用工具（本地+远程）"""
        tools = list(self._local_tools.values())
        for node_tools in self._remote_tools.values():
            tools.extend(node_tools.values())
        return tools
    
    def find_tool(self, name: str) -> Optional[MCPTool]:
        """查找工具"""
        if name in self._local_tools:
            return self._local_tools[name]
        
        for node_tools in self._remote_tools.values():
            if name in node_tools:
                return node_tools[name]
        
        return None
    
    def register_remote_tool(self, tool: MCPTool) -> bool:
        """注册远程工具"""
        provider = tool.provider_node
        if provider not in self._remote_tools:
            self._remote_tools[provider] = {}
        
        self._remote_tools[provider][tool.name] = tool
        return True
    
    def unregister_remote_tools(self, provider_node: str):
        """注销某节点的所有工具"""
        if provider_node in self._remote_tools:
            del self._remote_tools[provider_node]
    
    def is_local_tool(self, name: str) -> bool:
        """检查是否为本地工具"""
        return name in self._local_tools
    
    def get_tool_provider(self, name: str) -> Optional[str]:
        """获取工具提供者节点ID"""
        tool = self.find_tool(name)
        return tool.provider_node if tool else None
    
    async def execute_local(self, request: MCPRequest) -> MCPResponse:
        """执行本地工具"""
        start_time = time.time()
        
        if request.tool_name not in self._handlers:
            return MCPResponse(
                request_id=request.request_id,
                success=False,
                error=f"Tool '{request.tool_name}' not found"
            )
        
        try:
            handler = self._handlers[request.tool_name]
            result = await handler(request.arguments)
            
            return MCPResponse(
                request_id=request.request_id,
                success=True,
                result=result,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return MCPResponse(
                request_id=request.request_id,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def create_discover_message(self) -> Dict:
        """创建工具发现消息"""
        return {
            "type": MCPMessageType.TOOL_DISCOVER.value,
            "node_id": self.node_id,
            "tools": [t.to_dict() for t in self._local_tools.values()],
            "timestamp": time.time()
        }
    
    def create_register_message(self) -> Dict:
        """创建工具注册广播消息"""
        return {
            "type": MCPMessageType.SKILL_BROADCAST.value,
            "node_id": self.node_id,
            "tools": [t.to_dict() for t in self._local_tools.values()],
            "timestamp": time.time()
        }
    
    def create_call_request(self, tool_name: str, arguments: Dict) -> MCPRequest:
        """创建工具调用请求"""
        return MCPRequest(
            tool_name=tool_name,
            arguments=arguments,
            caller_node=self.node_id
        )
    
    def get_tools_by_tag(self, tag: str) -> List[MCPTool]:
        """按标签查找工具"""
        tools = []
        for tool in self.get_all_tools():
            if tag in tool.tags:
                tools.append(tool)
        return tools
    
    def get_tools_summary(self) -> str:
        """获取工具摘要（用于LLM提示）"""
        tools = self.get_all_tools()
        if not tools:
            return "No tools available"
        
        lines = ["Available Tools:"]
        for tool in tools:
            provider = "local" if tool.provider_node == self.node_id else f"remote({tool.provider_node[:8]})"
            lines.append(f"  - {tool.name} ({provider}): {tool.description}")
        
        return "\n".join(lines)


def create_default_tools(registry: MCPRegistry) -> None:
    """
    创建默认工具集
    
    这些是每个Agent都应该具备的基础能力
    """
    
    async def create_todo(args: Dict) -> Dict:
        return {"action": "create_todo", "title": args.get("title", "Untitled")}
    
    async def list_todos(args: Dict) -> Dict:
        return {"action": "list_todos"}
    
    async def complete_todo(args: Dict) -> Dict:
        return {"action": "complete_todo", "todo_id": args.get("todo_id")}
    
    registry.register_tool(
        name="create_todo",
        description="Create a new todo task",
        handler=create_todo,
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Todo title"}
            },
            "required": ["title"]
        },
        tags=["todo", "task"]
    )
    
    registry.register_tool(
        name="list_todos",
        description="List all todo tasks",
        handler=list_todos,
        input_schema={"type": "object", "properties": {}},
        tags=["todo", "query"]
    )
    
    registry.register_tool(
        name="complete_todo",
        description="Mark a todo as completed",
        handler=complete_todo,
        input_schema={
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "Todo ID to complete"}
            },
            "required": ["todo_id"]
        },
        tags=["todo", "task"]
    )
