"""
P2P网络层 - 基于libp2p的去中心化通信

核心功能:
1. GossipSub广播 - 高效的消息传播
2. 心跳机制 - 节点存活检测
3. 重同步机制 - 新节点加入时拉取全量数据
4. MCP over libp2p - 工具调用协议
5. 点对点直连 - 直接调用远程节点
6. 任务委派 - 发布任务让其他节点认领
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum

try:
    from libp2p import new_host
    from libp2p.pubsub import Pubsub
    from libp2p.pubsub.gossipsub import GossipSub
    from multiaddr import Multiaddr
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False
    print("Warning: libp2p not installed, using mock implementation")


class MessageType(Enum):
    CRDT_SYNC = "crdt_sync"
    HEARTBEAT = "heartbeat"
    SYNC_REQUEST = "sync_request"
    SYNC_FULL = "sync_full"
    MCP_TOOL_REGISTER = "mcp_tool_register"
    MCP_TOOL_CALL = "mcp_tool_call"
    MCP_TOOL_RESPONSE = "mcp_tool_response"
    BACKUP_ANNOUNCE = "backup_announce"
    NODE_JOIN = "node_join"
    NODE_LEAVE = "node_leave"
    CHAT = "chat"
    MUSCLE_ANNOUNCE = "muscle_announce"
    PRIVATE_CHAT = "private_chat"
    ANNOUNCE = "announce"
    
    SKILL_ANNOUNCE = "skill_announce"
    SKILL_METADATA_REQUEST = "skill_metadata_request"
    SKILL_METADATA_RESPONSE = "skill_metadata_response"
    SKILL_LOAD_REQUEST = "skill_load_request"
    SKILL_LOAD_RESPONSE = "skill_load_response"
    SKILL_TOOL_CALL = "skill_tool_call"
    SKILL_TOOL_RESPONSE = "skill_tool_response"
    
    REMOTE_MCP_ANNOUNCE = "remote_mcp_announce"
    REMOTE_MCP_CALL = "remote_mcp_call"
    REMOTE_MCP_RESPONSE = "remote_mcp_response"
    
    DIRECT_CALL = "direct_call"
    DIRECT_RESPONSE = "direct_response"
    
    TASK_DELEGATE = "task_delegate"
    TASK_CLAIM = "task_claim"
    TASK_RESULT = "task_result"


@dataclass
class P2PConfig:
    port: int = 0
    bootstrap_peers: List[str] = None
    heartbeat_interval: float = 3.0
    sync_interval: float = 10.0
    node_timeout: float = 15.0
    
    def __post_init__(self):
        if self.bootstrap_peers is None:
            self.bootstrap_peers = []


class MockP2PHost:
    """Mock host for testing without libp2p"""
    
    def __init__(self, node_id: str):
        self._id = node_id
        self._network = MockNetwork()
    
    def get_id(self):
        return MockPeerId(self._id)
    
    def get_network(self):
        return self._network
    
    def get_addrs(self):
        return [f"/ip4/127.0.0.1/tcp/0/p2p/{self._id}"]
    
    async def connect(self, addr):
        pass


class MockPeerId:
    def __init__(self, id_str: str):
        self._id = id_str
    
    def pretty(self):
        return self._id


class MockNetwork:
    def __init__(self):
        self._listening = False
    
    async def listen(self, addr):
        self._listening = True


class MockPubsub:
    def __init__(self, host, gossipsub):
        self._host = host
        self._topics: Dict[str, List] = {}
    
    async def subscribe(self, topic: str):
        if topic not in self._topics:
            self._topics[topic] = []
        return MockTopic(topic, self._topics[topic])


class MockTopic:
    def __init__(self, name: str, messages: List):
        self.name = name
        self._messages = messages
        self._published = []
    
    async def get(self):
        await asyncio.sleep(0.1)
        if self._published:
            msg = self._published.pop(0)
            return MockMessage(msg)
        await asyncio.sleep(1)
        return None
    
    async def publish(self, data: bytes):
        self._published.append(data)


class MockMessage:
    def __init__(self, data: bytes):
        self.data = data
        self.from_id = MockPeerId("mock_sender")


class P2PNetwork:
    """
    P2P网络管理器
    
    职责:
    1. 节点启动和连接
    2. 消息广播和接收
    3. 心跳维护
    4. 数据同步
    """
    
    TOPIC_CRDT = "crdt-todo-sync"
    TOPIC_MCP = "mcp-tools"
    TOPIC_HEARTBEAT = "heartbeat"
    
    def __init__(self, node_id: str, config: P2PConfig = None):
        self.node_id = node_id
        self.config = config or P2PConfig()
        
        self.host = None
        self.pubsub = None
        self.topic_crdt = None
        self.topic_mcp = None
        self.topic_heartbeat = None
        
        self._running = False
        self._handlers: Dict[str, List[Callable]] = {
            MessageType.CRDT_SYNC.value: [],
            MessageType.HEARTBEAT.value: [],
            MessageType.SYNC_REQUEST.value: [],
            MessageType.SYNC_FULL.value: [],
            MessageType.MCP_TOOL_REGISTER.value: [],
            MessageType.MCP_TOOL_CALL.value: [],
            MessageType.MCP_TOOL_RESPONSE.value: [],
            MessageType.BACKUP_ANNOUNCE.value: [],
            MessageType.SKILL_ANNOUNCE.value: [],
            MessageType.SKILL_METADATA_REQUEST.value: [],
            MessageType.SKILL_METADATA_RESPONSE.value: [],
            MessageType.SKILL_LOAD_REQUEST.value: [],
            MessageType.SKILL_LOAD_RESPONSE.value: [],
            MessageType.SKILL_TOOL_CALL.value: [],
            MessageType.SKILL_TOOL_RESPONSE.value: [],
            MessageType.REMOTE_MCP_ANNOUNCE.value: [],
            MessageType.REMOTE_MCP_CALL.value: [],
            MessageType.REMOTE_MCP_RESPONSE.value: [],
            MessageType.DIRECT_CALL.value: [],
            MessageType.DIRECT_RESPONSE.value: [],
            MessageType.TASK_DELEGATE.value: [],
            MessageType.TASK_CLAIM.value: [],
            MessageType.TASK_RESULT.value: [],
        }
        
        self._message_queue = asyncio.Queue()
        self._known_peers: Dict[str, float] = {}
        self._peer_addrs: Dict[str, str] = {}
        self._pending_direct_calls: Dict[str, asyncio.Future] = {}
        self._pending_tasks: Dict[str, asyncio.Future] = {}
    
    async def start(self) -> str:
        """启动P2P节点"""
        if not LIBP2P_AVAILABLE:
            return await self._start_mock()
        
        try:
            self.host = await new_host()
            port = self.config.port or 0
            
            await self.host.get_network().listen(
                Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
            )
            
            self.pubsub = Pubsub(self.host, GossipSub)
            
            self.topic_crdt = await self.pubsub.subscribe(self.TOPIC_CRDT)
            self.topic_mcp = await self.pubsub.subscribe(self.TOPIC_MCP)
            self.topic_heartbeat = await self.pubsub.subscribe(self.TOPIC_HEARTBEAT)
            
            for addr in self.config.bootstrap_peers:
                try:
                    await self.host.connect(Multiaddr(addr))
                    print(f"Connected to bootstrap: {addr}")
                except Exception as e:
                    print(f"Failed to connect to {addr}: {e}")
            
            self._running = True
            
            asyncio.create_task(self._message_loop())
            asyncio.create_task(self._heartbeat_loop())
            
            return self.host.get_id().pretty()
            
        except Exception as e:
            print(f"Failed to start libp2p: {e}")
            return await self._start_mock()
    
    async def _start_mock(self) -> str:
        """启动Mock模式"""
        self.host = MockP2PHost(self.node_id)
        self.pubsub = MockPubsub(self.host, None)
        
        self.topic_crdt = await self.pubsub.subscribe(self.TOPIC_CRDT)
        self.topic_mcp = await self.pubsub.subscribe(self.TOPIC_MCP)
        self.topic_heartbeat = await self.pubsub.subscribe(self.TOPIC_HEARTBEAT)
        
        self._running = True
        
        asyncio.create_task(self._message_loop())
        asyncio.create_task(self._heartbeat_loop())
        
        return self.node_id
    
    def get_peer_addr(self) -> str:
        """获取本节点的P2P地址"""
        if self.host:
            addrs = self.host.get_addrs()
            if addrs:
                return str(addrs[0])
        return f"/ip4/127.0.0.1/tcp/{self.config.port}/p2p/{self.node_id}"
    
    def on_message(self, msg_type: str, handler: Callable):
        """注册消息处理器"""
        if msg_type in self._handlers:
            self._handlers[msg_type].append(handler)
    
    async def broadcast_crdt(self, data: Dict):
        """广播CRDT状态更新"""
        message = {
            "type": MessageType.CRDT_SYNC.value,
            "node_id": self.node_id,
            "data": data,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def broadcast_heartbeat(self):
        """广播心跳"""
        message = {
            "type": MessageType.HEARTBEAT.value,
            "node_id": self.node_id,
            "timestamp": time.time()
        }
        await self._publish(self.topic_heartbeat, message)
    
    async def request_sync(self):
        """请求全量同步"""
        message = {
            "type": MessageType.SYNC_REQUEST.value,
            "node_id": self.node_id,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def send_full_sync(self, data: Dict, target_node: str = None):
        """发送全量数据"""
        message = {
            "type": MessageType.SYNC_FULL.value,
            "node_id": self.node_id,
            "data": data,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def broadcast_mcp_tools(self, tools: List[Dict]):
        """广播MCP工具注册"""
        message = {
            "type": MessageType.MCP_TOOL_REGISTER.value,
            "node_id": self.node_id,
            "tools": tools,
            "timestamp": time.time()
        }
        await self._publish(self.topic_mcp, message)
    
    async def call_remote_tool(self, request: Dict):
        """调用远程工具"""
        message = {
            "type": MessageType.MCP_TOOL_CALL.value,
            "node_id": self.node_id,
            "request": request,
            "timestamp": time.time()
        }
        await self._publish(self.topic_mcp, message)
    
    async def respond_tool_call(self, response: Dict):
        """响应工具调用"""
        message = {
            "type": MessageType.MCP_TOOL_RESPONSE.value,
            "node_id": self.node_id,
            "response": response,
            "timestamp": time.time()
        }
        await self._publish(self.topic_mcp, message)
    
    async def announce_backup(self, task_id: str, backup_data: Dict):
        """广播备份完成"""
        message = {
            "type": MessageType.BACKUP_ANNOUNCE.value,
            "node_id": self.node_id,
            "task_id": task_id,
            "backup_data": backup_data,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def _publish(self, topic, message: Dict):
        """发布消息"""
        if topic:
            try:
                data = json.dumps(message).encode()
                await topic.publish(data)
            except Exception as e:
                print(f"Publish error: {e}")
    
    async def _message_loop(self):
        """消息接收循环"""
        while self._running:
            try:
                await asyncio.gather(
                    self._read_topic(self.topic_crdt),
                    self._read_topic(self.topic_mcp),
                    self._read_topic(self.topic_heartbeat)
                )
            except Exception as e:
                if self._running:
                    print(f"Message loop error: {e}")
                await asyncio.sleep(1)
    
    async def _read_topic(self, topic):
        """读取单个topic的消息"""
        try:
            msg = await topic.get()
            if msg:
                sender_id = msg.from_id.pretty() if hasattr(msg.from_id, 'pretty') else str(msg.from_id)
                
                if sender_id == self.node_id:
                    return
                
                try:
                    data = json.loads(msg.data.decode())
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            pass
    
    async def _handle_message(self, message: Dict):
        """处理接收到的消息"""
        msg_type = message.get("type")
        sender = message.get("node_id")
        
        self._known_peers[sender] = time.time()
        
        if msg_type == MessageType.DIRECT_CALL.value:
            await self._handle_direct_call(message)
            return
        
        if msg_type == MessageType.DIRECT_RESPONSE.value:
            await self._handle_direct_response(message)
            return
        
        if msg_type == MessageType.TASK_DELEGATE.value:
            await self._handle_task_delegate(message)
            return
        
        if msg_type == MessageType.TASK_CLAIM.value:
            await self._handle_task_claim(message)
            return
        
        if msg_type == MessageType.TASK_RESULT.value:
            await self._handle_task_result(message)
            return
        
        handlers = self._handlers.get(msg_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                print(f"Handler error for {msg_type}: {e}")
    
    async def _heartbeat_loop(self):
        """心跳广播循环"""
        while self._running:
            await self.broadcast_heartbeat()
            await asyncio.sleep(self.config.heartbeat_interval)
    
    async def stop(self):
        """停止节点"""
        self._running = False
        if self.host and LIBP2P_AVAILABLE:
            try:
                await self.host.close()
            except:
                pass
    
    def get_known_peers(self) -> List[str]:
        """获取已知节点列表"""
        now = time.time()
        return [
            peer_id for peer_id, last_seen in self._known_peers.items()
            if now - last_seen < self.config.node_timeout
        ]
    
    def register_peer_addr(self, peer_id: str, addr: str):
        """注册节点地址"""
        self._peer_addrs[peer_id] = addr
    
    def get_peer_addr_by_id(self, peer_id: str) -> Optional[str]:
        """获取节点地址"""
        return self._peer_addrs.get(peer_id)
    
    async def direct_call(self, target_node: str, call_type: str, 
                          payload: Dict, timeout: float = 30.0) -> Dict:
        """
        点对点直接调用
        
        Args:
            target_node: 目标节点ID
            call_type: 调用类型 (skill_tool, mcp_tool, etc.)
            payload: 调用参数
            timeout: 超时时间
        
        Returns:
            调用结果
        """
        request_id = f"direct_{time.time_ns()}"
        
        future = asyncio.Future()
        self._pending_direct_calls[request_id] = future
        
        message = {
            "type": MessageType.DIRECT_CALL.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "target_node": target_node,
            "call_type": call_type,
            "payload": payload,
            "timestamp": time.time()
        }
        
        if LIBP2P_AVAILABLE and target_node in self._peer_addrs:
            try:
                addr = self._peer_addrs[target_node]
                if self.host:
                    await self.host.connect(Multiaddr(addr))
            except Exception as e:
                print(f"Direct connection failed: {e}")
        
        await self._publish(self.topic_crdt, message)
        
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            if request_id in self._pending_direct_calls:
                del self._pending_direct_calls[request_id]
            return {"error": "Direct call timeout", "request_id": request_id}
    
    async def respond_direct_call(self, request_id: str, target_node: str, result: Dict):
        """响应直接调用"""
        message = {
            "type": MessageType.DIRECT_RESPONSE.value,
            "node_id": self.node_id,
            "request_id": request_id,
            "target_node": target_node,
            "result": result,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def delegate_task(self, task_id: str, task_data: Dict, 
                            required_capabilities: List[str] = None,
                            timeout: float = 60.0) -> Dict:
        """
        委派任务 - 发布任务让其他节点认领
        
        Args:
            task_id: 任务ID
            task_data: 任务数据
            required_capabilities: 所需能力列表
            timeout: 等待认领超时
        
        Returns:
            认领结果
        """
        future = asyncio.Future()
        self._pending_tasks[task_id] = future
        
        message = {
            "type": MessageType.TASK_DELEGATE.value,
            "node_id": self.node_id,
            "task_id": task_id,
            "task_data": task_data,
            "required_capabilities": required_capabilities or [],
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
        
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            if task_id in self._pending_tasks:
                del self._pending_tasks[task_id]
            return {"error": "No node claimed the task", "task_id": task_id}
    
    async def claim_task(self, task_id: str, delegator_node: str):
        """认领任务"""
        message = {
            "type": MessageType.TASK_CLAIM.value,
            "node_id": self.node_id,
            "task_id": task_id,
            "delegator_node": delegator_node,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def submit_task_result(self, task_id: str, delegator_node: str, result: Dict):
        """提交任务结果"""
        message = {
            "type": MessageType.TASK_RESULT.value,
            "node_id": self.node_id,
            "task_id": task_id,
            "delegator_node": delegator_node,
            "result": result,
            "timestamp": time.time()
        }
        await self._publish(self.topic_crdt, message)
    
    async def _handle_direct_call(self, message: Dict):
        """处理直接调用请求"""
        target_node = message.get("target_node")
        if target_node != self.node_id:
            return
        
        request_id = message.get("request_id")
        call_type = message.get("call_type")
        payload = message.get("payload", {})
        sender = message.get("node_id")
        
        handlers = self._handlers.get(MessageType.DIRECT_CALL.value, [])
        result = {"error": "No handler for direct call"}
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
                break
            except Exception as e:
                result = {"error": str(e)}
        
        await self.respond_direct_call(request_id, sender, result)
    
    async def _handle_direct_response(self, message: Dict):
        """处理直接调用响应"""
        request_id = message.get("request_id")
        target_node = message.get("target_node")
        
        if target_node != self.node_id:
            return
        
        if request_id in self._pending_direct_calls:
            future = self._pending_direct_calls.pop(request_id)
            result = message.get("result", {})
            future.set_result(result)
    
    async def _handle_task_delegate(self, message: Dict):
        """处理任务委派"""
        task_id = message.get("task_id")
        task_data = message.get("task_data", {})
        required_capabilities = message.get("required_capabilities", [])
        delegator = message.get("node_id")
        
        handlers = self._handlers.get(MessageType.TASK_DELEGATE.value, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    can_handle = await handler(message)
                else:
                    can_handle = handler(message)
                
                if can_handle:
                    await self.claim_task(task_id, delegator)
                    break
            except Exception as e:
                print(f"Task delegate handler error: {e}")
    
    async def _handle_task_claim(self, message: Dict):
        """处理任务认领"""
        task_id = message.get("task_id")
        delegator = message.get("delegator_node")
        claimer = message.get("node_id")
        
        if delegator != self.node_id:
            return
        
        if task_id in self._pending_tasks:
            future = self._pending_tasks.pop(task_id)
            future.set_result({
                "claimed": True,
                "claimer": claimer,
                "task_id": task_id
            })
            print(f"📋 任务 {task_id} 被 {claimer} 认领")
    
    async def _handle_task_result(self, message: Dict):
        """处理任务结果"""
        task_id = message.get("task_id")
        delegator = message.get("delegator_node")
        result = message.get("result", {})
        executor = message.get("node_id")
        
        if delegator != self.node_id:
            return
        
        print(f"✅ 任务 {task_id} 完成，执行者: {executor}")
        
        handlers = self._handlers.get(MessageType.TASK_RESULT.value, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                print(f"Task result handler error: {e}")
