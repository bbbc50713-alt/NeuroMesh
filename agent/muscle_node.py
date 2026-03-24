"""
肌肉节点 (Muscle Node) - 纯资源执行节点

特征:
1. 无LLM，极轻量（几十MB内存）
2. 不订阅全局TodoList
3. 只暴露MCP工具接口
4. 通过心跳广播存在
5. 支持本地 Skills 和 MCP
6. 支持远程资源共享

适用场景:
- 树莓派、旧手机、IoT设备
- 数据库服务器、文件存储
- 任何需要物理执行的硬件
"""

import asyncio
import json
import time
import sys
import os
from typing import Dict, List, Callable, Any, Awaitable
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.p2p_network import P2PNetwork, P2PConfig, MessageType, LIBP2P_AVAILABLE
from core.skill_loader import SkillLoader
from core.mcp_client import MCPClientManager


@dataclass
class MuscleConfig:
    name: str
    port: int = 0
    bootstrap_peers: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    heartbeat_interval: float = 15.0
    
    mounted_skills: List[str] = field(default_factory=list)
    mounted_mcps: List[str] = field(default_factory=list)


ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


class MuscleNode:
    """
    肌肉节点 - 纯执行节点
    
    核心特点:
    1. 不参与任务调度决策
    2. 只响应大脑节点的RPC调用
    3. 极低资源消耗
    4. 物理级安全隔离
    5. 支持本地 Skills 和 MCP
    6. 支持远程资源共享
    """
    
    def __init__(self, config: MuscleConfig):
        self.config = config
        self.node_id = config.name
        
        self.tools: Dict[str, ToolHandler] = {}
        self.tool_schemas: Dict[str, Dict] = {}
        
        self.p2p = P2PNetwork(
            self.node_id,
            P2PConfig(
                port=config.port,
                bootstrap_peers=config.bootstrap_peers
            )
        )
        
        self._running = False
        
        self.skill_loader = SkillLoader()
        self.mcp_manager = MCPClientManager()
        
        self._pending_remote_requests: Dict[str, asyncio.Future] = {}
    
    def register_tool(
        self,
        name: str,
        handler: ToolHandler,
        description: str = "",
        input_schema: Dict = None
    ):
        """
        注册MCP工具
        
        Args:
            name: 工具名称 (如 mcp/camera_capture)
            handler: 异步处理函数
            description: 工具描述
            input_schema: 参数schema
        """
        self.tools[name] = handler
        self.tool_schemas[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema or {"type": "object", "properties": {}}
        }
        print(f"💪 注册工具: {name}")
    
    async def start(self) -> str:
        """启动肌肉节点"""
        peer_id = await self.p2p.start()
        
        self._running = True
        
        self.p2p.on_message(MessageType.MCP_TOOL_CALL.value, self._handle_tool_call)
        self.p2p.on_message(MessageType.SKILL_METADATA_REQUEST.value, self._handle_skill_metadata_request)
        self.p2p.on_message(MessageType.SKILL_LOAD_REQUEST.value, self._handle_skill_load_request)
        self.p2p.on_message(MessageType.SKILL_TOOL_CALL.value, self._handle_skill_tool_call)
        self.p2p.on_message(MessageType.REMOTE_MCP_CALL.value, self._handle_remote_mcp_call)
        
        self.p2p.on_message(MessageType.DIRECT_CALL.value, self._handle_direct_call)
        self.p2p.on_message(MessageType.TASK_DELEGATE.value, self._handle_task_delegate)
        
        await self._start_mounted_resources()
        
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._resource_broadcast_loop())
        
        skill_stats = self.skill_loader.get_stats()
        mcp_count = len(self.mcp_manager.clients)
        
        print(f"\n💪 肌肉节点已上线!")
        print(f"   Node ID: {peer_id}")
        print(f"   监听地址: {self.p2p.get_peer_addr()}")
        print(f"   本地工具: {list(self.tools.keys())}")
        print(f"   Skills: {skill_stats['total_skills']} 注册, {skill_stats['loaded_skills']} 加载")
        print(f"   MCP: {mcp_count} 个")
        print(f"   支持任务认领: 是")
        print(f"   等待大脑节点调用...\n")
        
        return peer_id
    
    async def _start_mounted_resources(self):
        """启动挂载的 Skills 和 MCP"""
        from core.mcp_manager import MCPManager
        from core.skills_manager import SkillManager
        
        mcp_manager = MCPManager()
        
        for mcp_name in self.config.mounted_mcps:
            server_config = mcp_manager.get_server(mcp_name)
            if server_config and not server_config.disabled:
                success = await self.mcp_manager.start_client(
                    name=mcp_name,
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.env
                )
                if success:
                    print(f"✅ 启动 MCP: {mcp_name}")
        
        skill_manager = SkillManager()
        
        for skill_name in self.config.mounted_skills:
            skill_config = skill_manager.get_skill(skill_name)
            if skill_config and skill_config.enabled:
                metadata = self.skill_loader.register_skill(skill_config.path)
                if metadata:
                    print(f"📋 注册 Skill: {skill_name}")
    
    async def _resource_broadcast_loop(self):
        """定期广播资源"""
        while self._running:
            await self._broadcast_resources()
            await asyncio.sleep(self.config.heartbeat_interval * 2)
    
    async def _broadcast_resources(self):
        """广播本地资源"""
        await self._broadcast_presence()
        await self._broadcast_skills()
        await self._broadcast_mcps()
    
    async def _broadcast_presence(self):
        """广播存在和能力"""
        message = {
            "type": MessageType.MUSCLE_ANNOUNCE.value,
            "node_id": self.node_id,
            "capabilities": list(self.tools.keys()),
            "schemas": self.tool_schemas,
            "timestamp": time.time()
        }
        
        await self.p2p._publish(self.p2p.topic_crdt, message)
    
    async def _broadcast_skills(self):
        """广播 Skills 元数据"""
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
    
    async def _broadcast_mcps(self):
        """广播 MCP 元数据"""
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
    
    async def _handle_tool_call(self, message: Dict):
        """处理工具调用请求"""
        request_data = message.get("request", {})
        caller = message.get("node_id")
        
        tool_name = request_data.get("tool_name")
        arguments = request_data.get("arguments", {})
        request_id = request_data.get("request_id")
        
        print(f"📞 收到调用请求: {tool_name} from {caller}")
        
        if tool_name not in self.tools:
            response = {
                "request_id": request_id,
                "success": False,
                "error": f"Tool '{tool_name}' not found"
            }
        else:
            try:
                handler = self.tools[tool_name]
                result = await handler(arguments)
                
                response = {
                    "request_id": request_id,
                    "success": True,
                    "result": result
                }
                print(f"✅ 工具执行成功: {tool_name}")
                
            except Exception as e:
                response = {
                    "request_id": request_id,
                    "success": False,
                    "error": str(e)
                }
                print(f"❌ 工具执行失败: {tool_name} - {e}")
        
        await self.p2p.respond_tool_call(response)
    
    async def _handle_skill_metadata_request(self, message: Dict):
        """处理 Skill 元数据请求"""
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        
        metadata = self.skill_loader.get_skill_metadata(skill_name)
        
        response = {
            "type": MessageType.SKILL_METADATA_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "skill_name": skill_name,
            "metadata": {
                "name": metadata.name,
                "description": metadata.description,
                "tool_count": metadata.tool_count,
                "has_script": metadata.has_script,
                "has_mcp": metadata.has_mcp
            } if metadata else None,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
        print(f"📤 发送 Skill 元数据: {skill_name} -> {sender}")
    
    async def _handle_skill_load_request(self, message: Dict):
        """处理 Skill 加载请求"""
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        
        print(f"📥 收到 Skill 加载请求: {skill_name} from {sender}")
        
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
        print(f"📤 发送 Skill 工具定义: {skill_name} -> {len(tool_definitions)} 个工具")
    
    async def _handle_skill_tool_call(self, message: Dict):
        """处理远程 Skill 工具调用"""
        sender = message.get("node_id")
        request_id = message.get("request_id")
        skill_name = message.get("skill_name")
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        
        print(f"📞 收到远程 Skill 调用: {tool_name} from {sender}")
        
        result = await self.skill_loader.call_tool(tool_name, arguments)
        
        response = {
            "type": MessageType.SKILL_TOOL_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "result": result,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
        print(f"📤 发送 Skill 工具结果: {tool_name}")
    
    async def _handle_remote_mcp_call(self, message: Dict):
        """处理远程 MCP 调用"""
        sender = message.get("node_id")
        request_id = message.get("request_id")
        mcp_name = message.get("mcp_name")
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        
        print(f"📞 收到远程 MCP 调用: {tool_name} from {sender}")
        
        result = await self.mcp_manager.call_tool(tool_name, arguments)
        
        response = {
            "type": MessageType.REMOTE_MCP_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "result": result,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, response)
        print(f"📤 发送 MCP 工具结果: {tool_name}")
    
    async def _handle_direct_call(self, message: Dict) -> Dict:
        """处理点对点直接调用"""
        call_type = message.get("call_type")
        payload = message.get("payload", {})
        sender = message.get("node_id")
        
        print(f"🔗 收到直连调用: {call_type} from {sender}")
        
        if call_type == "skill_tool":
            skill_name = payload.get("skill_name")
            tool_name = payload.get("tool_name")
            arguments = payload.get("arguments", {})
            
            result = await self.skill_loader.call_tool(tool_name, arguments)
            return result
        
        elif call_type == "mcp_tool":
            mcp_name = payload.get("mcp_name")
            tool_name = payload.get("tool_name")
            arguments = payload.get("arguments", {})
            
            result = await self.mcp_manager.call_tool(tool_name, arguments)
            return result
        
        elif call_type == "task_execute":
            task_id = payload.get("task_id")
            task_data = payload.get("task_data")
            
            result = await self._execute_delegated_task(task_id, task_data, sender)
            return result
        
        else:
            return {"error": f"Unknown call type: {call_type}"}
    
    async def _handle_task_delegate(self, message: Dict) -> bool:
        """处理任务委派，决定是否认领"""
        task_id = message.get("task_id")
        task_data = message.get("task_data", {})
        required_capabilities = message.get("required_capabilities", [])
        delegator = message.get("node_id")
        
        can_handle = self._check_capabilities(required_capabilities)
        
        if can_handle:
            print(f"📋 可以认领任务: {task_id}")
            return True
        
        return False
    
    def _check_capabilities(self, required_capabilities: List[str]) -> bool:
        """检查是否具备所需能力"""
        if not required_capabilities:
            return True
        
        all_capabilities = set(self.tools.keys())
        
        for skill_name, metadata in self.skill_loader.get_all_metadata().items():
            if metadata.has_script or metadata.has_mcp:
                for i in range(metadata.tool_count):
                    all_capabilities.add(f"skill_{skill_name}_tool_{i}")
        
        for mcp_name, client in self.mcp_manager.clients.items():
            if hasattr(client, 'get_tool_definitions'):
                for tool_def in client.get_tool_definitions():
                    tool_name = tool_def.get("function", {}).get("name", "")
                    if tool_name:
                        all_capabilities.add(tool_name)
        
        for cap in required_capabilities:
            if cap not in all_capabilities:
                return False
        
        return True
    
    async def _execute_delegated_task(self, task_id: str, task_data: Dict, 
                                       delegator: str) -> Dict:
        """执行委派的任务"""
        print(f"⚡ 执行委派任务: {task_id}")
        
        task_title = task_data.get("title", "Unknown")
        task_description = task_data.get("description", "")
        
        print(f"   任务: {task_title}")
        print(f"   描述: {task_description}")
        
        result = await self._find_and_execute_tool(task_title, task_description)
        
        await self.p2p.submit_task_result(task_id, delegator, result)
        
        return result
    
    async def _find_and_execute_tool(self, title: str, description: str) -> Dict:
        """查找并执行工具"""
        title_lower = title.lower()
        desc_lower = description.lower()
        
        for tool_name, handler in self.tools.items():
            if tool_name.lower() in title_lower or tool_name.lower() in desc_lower:
                print(f"   使用工具: {tool_name}")
                try:
                    result = await handler({})
                    return {"success": True, "tool": tool_name, "result": result}
                except Exception as e:
                    return {"success": False, "error": str(e)}
        
        loaded_tools = self.skill_loader.get_loaded_tools()
        for tool in loaded_tools:
            if tool.name.lower() in title_lower or tool.name.lower() in desc_lower:
                print(f"   使用 Skill 工具: {tool.name}")
                result = await self.skill_loader.call_tool(tool.name, {})
                return result
        
        return {"success": False, "error": "No matching tool found"}
    
    async def stop(self):
        """停止节点"""
        self._running = False
        
        await self.mcp_manager.stop_all()
        await self.p2p.stop()
        print(f"💪 肌肉节点 [{self.node_id}] 已下线")
    
    async def _heartbeat_loop(self):
        """心跳广播循环"""
        while self._running:
            await self._broadcast_presence()
            await asyncio.sleep(self.config.heartbeat_interval)
    
    def get_status(self) -> Dict:
        """获取状态"""
        skill_stats = self.skill_loader.get_stats()
        
        return {
            "node_id": self.node_id,
            "tools": list(self.tools.keys()),
            "skill_stats": skill_stats,
            "mcp_count": len(self.mcp_manager.clients),
            "mounted_skills": self.config.mounted_skills,
            "mounted_mcps": self.config.mounted_mcps
        }


def create_camera_muscle(name: str = "Muscle-Camera", port: int = 10010) -> MuscleNode:
    """创建摄像头肌肉节点示例"""
    
    config = MuscleConfig(
        name=name,
        port=port,
        capabilities=["mcp/camera_capture", "mcp/camera_stream"]
    )
    
    node = MuscleNode(config)
    
    async def capture_image(args: Dict) -> Dict:
        print("📸 正在拍照...")
        await asyncio.sleep(1)
        return {
            "status": "success",
            "image_data": "base64_encoded_image_data...",
            "resolution": args.get("resolution", "1080p"),
            "timestamp": time.time()
        }
    
    async def stream_video(args: Dict) -> Dict:
        print("📹 开始视频流...")
        return {
            "status": "streaming",
            "stream_id": "stream_123",
            "fps": args.get("fps", 30)
        }
    
    node.register_tool(
        name="mcp/camera_capture",
        handler=capture_image,
        description="Capture image from camera",
        input_schema={
            "type": "object",
            "properties": {
                "resolution": {"type": "string", "default": "1080p"}
            }
        }
    )
    
    node.register_tool(
        name="mcp/camera_stream",
        handler=stream_video,
        description="Start video stream from camera",
        input_schema={
            "type": "object",
            "properties": {
                "fps": {"type": "integer", "default": 30}
            }
        }
    )
    
    return node


def create_database_muscle(name: str = "Muscle-Database", port: int = 10011) -> MuscleNode:
    """创建数据库肌肉节点示例"""
    
    config = MuscleConfig(
        name=name,
        port=port,
        capabilities=["mcp/sql_query", "mcp/sql_insert"]
    )
    
    node = MuscleNode(config)
    
    async def query_database(args: Dict) -> Dict:
        sql = args.get("sql", "")
        
        if "DROP" in sql.upper() or "DELETE" in sql.upper():
            return {
                "status": "rejected",
                "error": "Dangerous operation blocked by muscle node"
            }
        
        print(f"🔍 执行查询: {sql}")
        await asyncio.sleep(0.5)
        
        return {
            "status": "success",
            "rows": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"}
            ],
            "row_count": 2
        }
    
    async def insert_database(args: Dict) -> Dict:
        print(f"📝 执行插入...")
        await asyncio.sleep(0.3)
        
        return {
            "status": "success",
            "affected_rows": 1
        }
    
    node.register_tool(
        name="mcp/sql_query",
        handler=query_database,
        description="Execute SQL SELECT query",
        input_schema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT SQL query"}
            },
            "required": ["sql"]
        }
    )
    
    node.register_tool(
        name="mcp/sql_insert",
        handler=insert_database,
        description="Execute SQL INSERT",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "data": {"type": "object"}
            },
            "required": ["table", "data"]
        }
    )
    
    return node


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Start a Muscle Node")
    parser.add_argument("--type", choices=["camera", "database", "custom"], default="camera")
    parser.add_argument("--name", default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--bootstrap", nargs="*", default=[])
    
    args = parser.parse_args()
    
    if args.type == "camera":
        node = create_camera_muscle(
            name=args.name or "Muscle-Camera",
            port=args.port
        )
    elif args.type == "database":
        node = create_database_muscle(
            name=args.name or "Muscle-Database",
            port=args.port
        )
    else:
        config = MuscleConfig(
            name=args.name or "Muscle-Custom",
            port=args.port,
            bootstrap_peers=args.bootstrap
        )
        node = MuscleNode(config)
    
    if args.bootstrap:
        node.config.bootstrap_peers = args.bootstrap
    
    try:
        await node.start()
        
        while True:
            await asyncio.sleep(10)
            print(f"💪 心跳: {node.node_id} 在线, 工具: {list(node.tools.keys())}")
            
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
