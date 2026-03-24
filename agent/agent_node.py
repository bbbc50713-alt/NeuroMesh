"""
Agent核心模块 - 多智能体协作节点

核心能力:
1. 任务抢占和执行
2. 失败恢复和任务回收
3. 备份广播机制
4. MCP工具集成
"""

import asyncio
import json
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.crdt_engine import CRDTStore, TodoItem, TaskStatus
from core.mcp_protocol import MCPRegistry, MCPTool, MCPRequest, MCPResponse, create_default_tools
from network.p2p_network import P2PNetwork, P2PConfig, MessageType


class AgentState(Enum):
    IDLE = "idle"
    WORKING = "working"
    BACKUP = "backup"
    OFFLINE = "offline"


@dataclass
class AgentConfig:
    name: str
    port: int = 0
    bootstrap_peers: List[str] = field(default_factory=list)
    lease_seconds: int = 30
    heartbeat_timeout: float = 15.0
    work_interval: float = 2.0
    capabilities: List[str] = field(default_factory=list)
    server_url: str = ""


class Agent:
    """
    多智能体协作节点
    
    核心职责:
    1. CRDT状态管理 - 维护本地todo副本
    2. P2P通信 - 与其他节点同步
    3. 任务执行 - 抢占并完成任务
    4. 工具提供 - 通过MCP协议暴露能力
    5. 备份机制 - 任务状态备份广播
    """
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.node_id = config.name
        
        self.crdt_store = CRDTStore(self.node_id)
        self.mcp_registry = MCPRegistry(self.node_id)
        self.p2p_network = P2PNetwork(
            self.node_id,
            P2PConfig(
                port=config.port,
                bootstrap_peers=config.bootstrap_peers,
                node_timeout=config.heartbeat_timeout
            )
        )
        
        self.state = AgentState.IDLE
        self.current_task: Optional[TodoItem] = None
        self._running = False
        self._task_handlers: Dict[str, Callable] = {}
        
        self._setup_handlers()
        self._register_default_tools()
    
    def _setup_handlers(self):
        """设置消息处理器"""
        self.p2p_network.on_message(MessageType.CRDT_SYNC.value, self._handle_crdt_sync)
        self.p2p_network.on_message(MessageType.HEARTBEAT.value, self._handle_heartbeat)
        self.p2p_network.on_message(MessageType.SYNC_REQUEST.value, self._handle_sync_request)
        self.p2p_network.on_message(MessageType.SYNC_FULL.value, self._handle_sync_full)
        self.p2p_network.on_message(MessageType.MCP_TOOL_REGISTER.value, self._handle_mcp_register)
        self.p2p_network.on_message(MessageType.MCP_TOOL_CALL.value, self._handle_mcp_call)
        self.p2p_network.on_message(MessageType.MCP_TOOL_RESPONSE.value, self._handle_mcp_response)
        self.p2p_network.on_message(MessageType.BACKUP_ANNOUNCE.value, self._handle_backup)
    
    def _register_default_tools(self):
        """注册默认工具"""
        create_default_tools(self.mcp_registry)
        
        async def get_status(args: Dict) -> Dict:
            return {
                "agent": self.node_id,
                "state": self.state.value,
                "tasks_count": len(self.crdt_store.todos),
                "current_task": self.current_task.id if self.current_task else None
            }
        
        self.mcp_registry.register_tool(
            name="get_agent_status",
            description="Get current agent status and task info",
            handler=get_status,
            tags=["agent", "status"]
        )
    
    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        input_schema: Dict = None,
        tags: List[str] = None
    ):
        """注册自定义工具"""
        return self.mcp_registry.register_tool(
            name=name,
            description=description,
            handler=handler,
            input_schema=input_schema,
            tags=tags
        )
    
    def register_task_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self._task_handlers[task_type] = handler
    
    async def start(self) -> str:
        """启动Agent"""
        peer_id = await self.p2p_network.start()
        
        self._running = True
        
        asyncio.create_task(self._work_loop())
        asyncio.create_task(self._recovery_loop())
        asyncio.create_task(self._sync_with_server_loop())
        
        await asyncio.sleep(1)
        await self.p2p_network.request_sync()
        
        await self._broadcast_tools()
        
        print(f"Agent [{self.node_id}] started. Peer ID: {peer_id}")
        print(f"Listening at: {self.p2p_network.get_peer_addr()}")
        
        return peer_id
    
    async def stop(self):
        """停止Agent"""
        self._running = False
        
        if self.current_task:
            await self._release_task(self.current_task.id)
        
        await self.p2p_network.stop()
        print(f"Agent [{self.node_id}] stopped")
    
    async def create_todo(self, title: str, metadata: Dict = None) -> TodoItem:
        """创建新任务"""
        todo = self.crdt_store.create_todo(title, metadata)
        
        await self._broadcast_todo(todo)
        
        print(f"[{self.node_id}] Created todo: {title}")
        return todo
    
    async def _broadcast_todo(self, todo: TodoItem):
        """广播任务状态"""
        await self.p2p_network.broadcast_crdt(todo.to_dict())
        
        if self.config.server_url:
            await self._sync_to_server(todo.to_dict())
    
    async def _work_loop(self):
        """工作循环 - 抢占并执行任务"""
        while self._running:
            try:
                await self._try_work()
                await asyncio.sleep(self.config.work_interval)
            except Exception as e:
                print(f"[{self.node_id}] Work loop error: {e}")
                await asyncio.sleep(1)
    
    async def _try_work(self):
        """尝试抢占并执行任务"""
        if self.current_task:
            return
        
        pending_todos = self.crdt_store.get_pending_todos()
        
        for todo in pending_todos:
            if self.crdt_store.try_lock_task(todo.id, self.config.lease_seconds):
                self.current_task = self.crdt_store.todos[todo.id]
                self.state = AgentState.WORKING
                
                await self._broadcast_todo(self.current_task)
                
                print(f"[{self.node_id}] Locked task: {todo.title}")
                
                await self._broadcast_backup(todo.id, {"status": "started"})
                
                try:
                    await self._execute_task(self.current_task)
                    
                    self.crdt_store.complete_task(todo.id)
                    await self._broadcast_todo(self.crdt_store.todos[todo.id])
                    
                    print(f"[{self.node_id}] Completed task: {todo.title}")
                    
                    await self._broadcast_backup(todo.id, {"status": "completed"})
                    
                except Exception as e:
                    print(f"[{self.node_id}] Task failed: {e}")
                    await self._release_task(todo.id)
                
                finally:
                    self.current_task = None
                    self.state = AgentState.IDLE
                
                break
    
    async def _execute_task(self, todo: TodoItem):
        """执行任务"""
        task_type = todo.metadata.get("type", "default")
        
        if task_type in self._task_handlers:
            handler = self._task_handlers[task_type]
            if asyncio.iscoroutinefunction(handler):
                await handler(todo)
            else:
                handler(todo)
        else:
            await self._default_task_handler(todo)
    
    async def _default_task_handler(self, todo: TodoItem):
        """默认任务处理器"""
        print(f"[{self.node_id}] Processing: {todo.title}")
        await asyncio.sleep(2)
    
    async def _release_task(self, todo_id: str):
        """释放任务"""
        if self.crdt_store.release_task(todo_id):
            await self._broadcast_todo(self.crdt_store.todos[todo_id])
            print(f"[{self.node_id}] Released task: {todo_id}")
    
    async def _recovery_loop(self):
        """恢复循环 - 检测并恢复死节点任务"""
        while self._running:
            try:
                recovered = self.crdt_store.recover_dead_tasks(self.config.heartbeat_timeout)
                
                for todo_id in recovered:
                    print(f"[{self.node_id}] Recovered dead task: {todo_id}")
                    await self._broadcast_todo(self.crdt_store.todos[todo_id])
                
                await asyncio.sleep(self.config.heartbeat_timeout)
            except Exception as e:
                print(f"[{self.node_id}] Recovery loop error: {e}")
                await asyncio.sleep(5)
    
    async def _sync_with_server_loop(self):
        """与中心服务器同步"""
        if not self.config.server_url:
            return
        
        while self._running:
            try:
                await asyncio.sleep(10)
                all_todos = self.crdt_store.get_all_todos()
                for todo_data in all_todos.values():
                    await self._sync_to_server(todo_data)
            except Exception as e:
                print(f"[{self.node_id}] Server sync error: {e}")
    
    async def _sync_to_server(self, todo_data: Dict):
        """同步到服务器"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.config.server_url}/sync",
                    json=todo_data,
                    timeout=5.0
                )
        except Exception as e:
            pass
    
    async def _broadcast_tools(self):
        """广播工具注册"""
        tools = [t.to_dict() for t in self.mcp_registry.get_local_tools()]
        await self.p2p_network.broadcast_mcp_tools(tools)
    
    async def _broadcast_backup(self, task_id: str, backup_data: Dict):
        """广播备份状态"""
        await self.p2p_network.announce_backup(task_id, backup_data)
    
    async def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        """调用工具（本地或远程）"""
        tool = self.mcp_registry.find_tool(tool_name)
        
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found")
        
        if self.mcp_registry.is_local_tool(tool_name):
            request = self.mcp_registry.create_call_request(tool_name, arguments)
            response = await self.mcp_registry.execute_local(request)
            if response.success:
                return response.result
            else:
                raise Exception(response.error)
        else:
            return await self._call_remote_tool(tool, arguments)
    
    async def _call_remote_tool(self, tool: MCPTool, arguments: Dict) -> Any:
        """调用远程工具"""
        request = self.mcp_registry.create_call_request(tool.name, arguments)
        
        await self.p2p_network.call_remote_tool(request.to_dict())
        
        return {"status": "request_sent", "tool": tool.name, "provider": tool.provider_node}
    
    async def _handle_crdt_sync(self, message: Dict):
        """处理CRDT同步消息"""
        data = message.get("data")
        if data:
            if self.crdt_store.merge(data):
                print(f"[{self.node_id}] CRDT updated: {data.get('id', 'unknown')}")
    
    async def _handle_heartbeat(self, message: Dict):
        """处理心跳消息"""
        sender = message.get("node_id")
        self.crdt_store.update_heartbeat(sender)
    
    async def _handle_sync_request(self, message: Dict):
        """处理同步请求"""
        all_todos = self.crdt_store.get_all_todos()
        if all_todos:
            await self.p2p_network.send_full_sync(all_todos)
    
    async def _handle_sync_full(self, message: Dict):
        """处理全量同步"""
        data = message.get("data", {})
        count = self.crdt_store.merge_batch(data)
        if count > 0:
            print(f"[{self.node_id}] Full sync: merged {count} todos")
    
    async def _handle_mcp_register(self, message: Dict):
        """处理MCP工具注册"""
        sender = message.get("node_id")
        tools = message.get("tools", [])
        
        for tool_data in tools:
            tool = MCPTool.from_dict(tool_data)
            self.mcp_registry.register_remote_tool(tool)
        
        print(f"[{self.node_id}] Registered {len(tools)} tools from {sender}")
    
    async def _handle_mcp_call(self, message: Dict):
        """处理MCP工具调用"""
        request_data = message.get("request", {})
        request = MCPRequest.from_dict(request_data)
        
        if self.mcp_registry.is_local_tool(request.tool_name):
            response = await self.mcp_registry.execute_local(request)
            await self.p2p_network.respond_tool_call(response.to_dict())
    
    async def _handle_mcp_response(self, message: Dict):
        """处理MCP工具响应"""
        response_data = message.get("response", {})
        print(f"[{self.node_id}] Tool response: {response_data}")
    
    async def _handle_backup(self, message: Dict):
        """处理备份广播"""
        task_id = message.get("task_id")
        backup_data = message.get("backup_data")
        sender = message.get("node_id")
        
        print(f"[{self.node_id}] Backup from {sender}: task={task_id}, data={backup_data}")
    
    def get_status(self) -> Dict:
        """获取Agent状态"""
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "current_task": self.current_task.to_dict() if self.current_task else None,
            "stats": self.crdt_store.get_stats(),
            "tools_count": len(self.mcp_registry.get_all_tools()),
            "known_peers": self.p2p_network.get_known_peers()
        }
    
    def print_status(self):
        """打印状态"""
        stats = self.crdt_store.get_stats()
        print(f"\n{'='*50}")
        print(f"Agent: {self.node_id}")
        print(f"State: {self.state.value}")
        print(f"Tasks: {stats['total']} (pending: {stats['pending']}, in_progress: {stats['in_progress']}, done: {stats['done']})")
        print(f"Alive nodes: {stats['alive_nodes']}")
        print(f"Tools: {len(self.mcp_registry.get_all_tools())}")
        
        if self.current_task:
            print(f"Current task: {self.current_task.title}")
        
        print(f"{'='*50}\n")
