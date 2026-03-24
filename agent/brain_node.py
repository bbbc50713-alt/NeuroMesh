"""
大脑节点 (Brain Node) - 主控决策节点

特征:
1. 挂载LLM，具备推理、规划、调度能力
2. 订阅全局TodoList
3. 维护肌肉节点注册表
4. 抢占任务并创建私有子网
5. 支持聊天室功能
6. 通过 MCP/Skills 执行任务

核心职责:
- 任务抢占与调度
- 私有子网管理
- 肌肉节点调用
- 人机交互
- MCP/Skills 工具调用
"""

import asyncio
import json
import time
import sys
import os
import subprocess
import shutil
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.crdt_engine_v2 import EnhancedCRDTStore, Task, TaskState, ChatMessage
from core.mcp_client import MCPClientManager
from core.skill_loader import SkillLoader
from core.remote_resource_manager import RemoteResourceManager
from network.p2p_network import P2PNetwork, P2PConfig, MessageType, LIBP2P_AVAILABLE


class BrainState(Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING_MUSCLE = "waiting_muscle"


@dataclass
class BrainConfig:
    name: str
    port: int = 0
    bootstrap_peers: List[str] = field(default_factory=list)
    server_url: str = ""
    lease_duration: int = 300
    heartbeat_timeout: float = 15.0
    work_interval: float = 2.0
    
    # LLM 配置
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4"
    
    # 挂载的 MCP 和 Skills
    mounted_mcps: List[str] = field(default_factory=list)
    mounted_skills: List[str] = field(default_factory=list)


class LLMClient:
    """LLM 客户端"""
    
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = None
    
    async def _get_client(self):
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(timeout=120.0)
            except ImportError:
                pass
        return self._client
    
    async def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        """调用 LLM"""
        if not self.base_url or not self.api_key:
            return {"error": "LLM not configured"}
        
        client = await self._get_client()
        if not client:
            return {"error": "httpx not installed"}
        
        try:
            payload = {
                "model": self.model,
                "messages": messages
            }
            if tools:
                payload["tools"] = tools
            
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"LLM API error: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def close(self):
        if self._client:
            await self._client.aclose()


class TaskExecutor:
    """
    任务执行器 - 通过 MCP/Skills 执行任务（支持渐进式加载和远程资源）
    
    执行流程:
    1. LLM 分析任务，选择合适的工具
    2. 如果选择的是未加载的 Skill，自动加载
    3. 如果选择的是远程工具，调用远程节点
    4. 调用 MCP Server 或 Skill 执行
    5. 返回执行结果
    
    渐进式加载特性:
    - 工具定义包含已加载和未加载的 Skills
    - 未加载的 Skills 显示为占位工具
    - 选择时自动加载对应的 Skill
    
    远程资源特性:
    - 工具定义包含远程节点的 Skills 和 MCP
    - 远程工具名称以 "remote_" 开头
    - 自动路由到正确的远程节点
    """
    
    def __init__(self, brain_node):
        self.brain = brain_node
        self.mcp_manager: MCPClientManager = brain_node.mcp_manager
        self.skill_loader: SkillLoader = brain_node.skill_loader
        self.remote_manager = None
    
    async def execute(self, task: Task) -> Dict:
        """执行任务 - 通过 MCP/Skills（支持渐进式加载和远程资源）"""
        
        self.remote_manager = self.brain.remote_manager
        
        tools = self._get_available_tools()
        
        if not tools:
            return {"success": False, "error": "没有可用的工具，请先挂载并启动 MCP 或 Skills"}
        
        if not self.brain.llm_client or not self.brain.llm_client.api_key:
            return {"success": False, "error": "LLM 未配置，无法分析任务"}
        
        tool_call = await self._select_tool_with_llm(task, tools)
        
        if not tool_call:
            return {"success": False, "error": "LLM 未能选择合适的工具"}
        
        tool_name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})
        
        print(f"🔧 调用工具: {tool_name}")
        print(f"   参数: {json.dumps(arguments, ensure_ascii=False)}")
        
        if tool_name.startswith("remote_"):
            return await self._execute_remote_tool(tool_name, arguments)
        
        if tool_name.startswith("skill_"):
            tool = await self.skill_loader.ensure_tool_loaded(tool_name)
            
            if tool is None:
                if tool_name.endswith("_load"):
                    skill_name = tool_name.replace("skill_", "").replace("_load", "")
                    print(f"📥 按需加载 Skill: {skill_name}")
                    await self.skill_loader.load_skill_full(skill_name)
                    return await self.execute(task)
                else:
                    return {"success": False, "error": f"无法加载工具: {tool_name}"}
            
            if tool.tool_type == "mcp" and tool.mcp_config:
                mcp_server_name = f"skill_{tool.skill_name}"
                if mcp_server_name not in self.mcp_manager.clients:
                    print(f"🚀 动态启动 Skill MCP: {mcp_server_name}")
                    await self.mcp_manager.start_client(
                        name=mcp_server_name,
                        command=tool.mcp_config.get("command", ""),
                        args=tool.mcp_config.get("args", []),
                        env=tool.mcp_config.get("env", {})
                    )
                    await asyncio.sleep(1)
                
                result = await self.mcp_manager.call_tool(tool_name, arguments)
            else:
                result = await self.skill_loader.call_tool(tool_name, arguments)
        else:
            result = await self.mcp_manager.call_tool(tool_name, arguments)
        
        if result.get("success"):
            return {
                "success": True,
                "tool": tool_name,
                "result": result.get("result"),
                "message": f"工具 {tool_name} 执行成功"
            }
        else:
            return {
                "success": False,
                "tool": tool_name,
                "error": result.get("error", "执行失败")
            }
    
    async def _execute_remote_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """执行远程工具"""
        if not self.remote_manager:
            return {"success": False, "error": "远程资源管理器未初始化"}
        
        remote_tool = self.remote_manager.find_remote_tool(tool_name)
        
        if not remote_tool:
            return {"success": False, "error": f"远程工具不存在: {tool_name}"}
        
        target_node = remote_tool.node_id
        resource_name = remote_tool.resource_name
        
        print(f"🌐 调用远程工具: {tool_name}@{target_node}")
        
        if remote_tool.resource_type.value == "skill":
            result = await self.remote_manager.call_remote_skill_tool(
                target_node=target_node,
                skill_name=resource_name,
                tool_name=tool_name.replace(f"remote_{target_node}_", "skill_"),
                arguments=arguments
            )
        else:
            result = await self.remote_manager.call_remote_mcp_tool(
                target_node=target_node,
                mcp_name=resource_name,
                tool_name=tool_name.replace(f"remote_{target_node}_", ""),
                arguments=arguments
            )
        
        if result.get("success"):
            return {
                "success": True,
                "tool": tool_name,
                "result": result.get("result"),
                "message": f"远程工具 {tool_name}@{target_node} 执行成功"
            }
        else:
            return {
                "success": False,
                "tool": tool_name,
                "error": result.get("error", "远程执行失败")
            }
    
    def _get_available_tools(self) -> List[Dict]:
        """
        获取所有可用工具（MCP + Skills + 远程资源）
        
        包含:
        1. MCP 工具（已启动的）
        2. 已加载的 Skill 工具
        3. 未加载的 Skill 占位工具（用于渐进式加载）
        4. 远程节点的 Skills 工具
        5. 远程节点的 MCP 工具
        """
        tools = []
        
        tools.extend(self.mcp_manager.get_all_tools())
        
        tools.extend(self.skill_loader.get_tool_definitions())
        
        if self.remote_manager:
            tools.extend(self.remote_manager.get_remote_tools())
        
        return tools
    
    async def _select_tool_with_llm(self, task: Task, tools: List[Dict]) -> Optional[Dict]:
        """LLM 选择工具并生成参数"""
        
        system_prompt = """你是一个任务执行助手。用户会给你一个任务描述，你需要：
1. 分析任务意图
2. 从可用工具中选择最合适的工具
3. 生成工具调用参数

注意：
- 工具名以 "skill_" 开头的是本地 Skill 工具
- 工具名以 "remote_" 开头的是远程节点的工具
- 工具描述包含 "[未加载]" 的是尚未加载的 Skill，选择后会自动加载
- 工具描述包含 "[远程:节点名]" 的是远程节点提供的工具
- 请根据任务需求选择最合适的工具，优先选择本地工具

请直接返回 JSON 格式的工具调用：
{"name": "工具名", "arguments": {...参数...}}

如果没有合适的工具，返回：
{"error": "原因"}"""

        user_message = f"""任务: {task.metadata.title}
描述: {task.metadata.description or '无'}

可用工具:
{json.dumps(tools, ensure_ascii=False, indent=2)}

请选择工具并生成参数。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        response = await self.brain.llm_client.chat(messages)
        
        if "error" in response:
            print(f"❌ LLM 调用失败: {response['error']}")
            return None
        
        try:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 尝试解析 JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                if "error" not in result:
                    return result
                else:
                    print(f"❌ LLM 返回错误: {result['error']}")
        except Exception as e:
            print(f"❌ 解析 LLM 响应失败: {e}")
        
        return None


class BrainNode:
    """
    大脑节点 - 主控决策节点
    
    核心能力:
    1. CRDT状态管理
    2. 任务抢占与调度
    3. 私有子网管理
    4. 肌肉节点发现与调用
    5. 聊天室功能
    6. LLM 集成
    7. MCP/Skills 工具调用
    8. 远程资源发现与调用
    """
    
    def __init__(self, config: BrainConfig):
        self.config = config
        self.node_id = config.name
        
        self.crdt = EnhancedCRDTStore(self.node_id)
        
        self.p2p = P2PNetwork(
            self.node_id,
            P2PConfig(
                port=config.port,
                bootstrap_peers=config.bootstrap_peers,
                node_timeout=config.heartbeat_timeout
            )
        )
        
        self.state = BrainState.IDLE
        self.current_task: Optional[Task] = None
        self._running = False
        
        self.active_subnets: Dict[str, Any] = {}
        self._task_handlers: Dict[str, Callable] = {}
        self._pending_tool_calls: Dict[str, asyncio.Future] = {}
        
        # LLM 客户端
        self.llm_client: Optional[LLMClient] = None
        if config.llm_base_url and config.llm_api_key:
            self.llm_client = LLMClient(
                base_url=config.llm_base_url,
                api_key=config.llm_api_key,
                model=config.llm_model
            )
        
        # MCP 客户端管理器
        self.mcp_manager = MCPClientManager()
        
        # Skill 加载器
        self.skill_loader = SkillLoader()
        
        # 远程资源管理器
        self.remote_manager: Optional[RemoteResourceManager] = None
        
        # 任务执行器
        self.executor = TaskExecutor(self)
    
    async def start(self) -> str:
        """启动大脑节点"""
        peer_id = await self.p2p.start()
        
        self._running = True
        
        self.p2p.on_message(MessageType.CRDT_SYNC.value, self._handle_crdt_sync)
        self.p2p.on_message(MessageType.HEARTBEAT.value, self._handle_heartbeat)
        self.p2p.on_message(MessageType.SYNC_REQUEST.value, self._handle_sync_request)
        self.p2p.on_message(MessageType.SYNC_FULL.value, self._handle_sync_full)
        self.p2p.on_message(MessageType.MCP_TOOL_REGISTER.value, self._handle_muscle_announce)
        self.p2p.on_message(MessageType.MCP_TOOL_RESPONSE.value, self._handle_tool_response)
        self.p2p.on_message(MessageType.BACKUP_ANNOUNCE.value, self._handle_backup)
        
        # 初始化远程资源管理器
        self.remote_manager = RemoteResourceManager(
            node_id=self.node_id,
            p2p_network=self.p2p,
            skill_loader=self.skill_loader,
            mcp_manager=self.mcp_manager
        )
        
        # 启动挂载的 MCP
        await self._start_mounted_mcps()
        
        # 广播本地资源
        await self.remote_manager.broadcast_local_skills()
        await self.remote_manager.broadcast_local_mcps()
        
        asyncio.create_task(self._work_loop())
        asyncio.create_task(self._recovery_loop())
        asyncio.create_task(self._sync_with_server_loop())
        asyncio.create_task(self._resource_broadcast_loop())
        
        await asyncio.sleep(1)
        await self.p2p.request_sync()
        
        llm_status = "✅ 已配置" if self.llm_client else "❌ 未配置"
        mcp_count = len(self.mcp_manager.clients)
        remote_stats = self.remote_manager.get_stats()
        
        print(f"\n🧠 大脑节点已上线!")
        print(f"   Node ID: {peer_id}")
        print(f"   监听地址: {self.p2p.get_peer_addr()}")
        print(f"   租约时长: {self.config.lease_duration}秒")
        print(f"   LLM状态: {llm_status}")
        if self.llm_client:
            print(f"   LLM模型: {self.config.llm_model}")
        print(f"   已启动MCP: {mcp_count}个")
        print(f"   挂载MCP: {len(self.config.mounted_mcps)}个")
        print(f"   挂载Skills: {len(self.config.mounted_skills)}个")
        print(f"   远程资源: Skills={remote_stats['remote_skills']}, MCPs={remote_stats['remote_mcps']}")
        print(f"   等待任务...\n")
        
        return peer_id
    
    async def _resource_broadcast_loop(self):
        """定期广播本地资源"""
        while self._running:
            await asyncio.sleep(60)
            if self.remote_manager:
                await self.remote_manager.broadcast_local_skills()
                await self.remote_manager.broadcast_local_mcps()
    
    async def _start_mounted_mcps(self):
        """
        启动挂载的 MCP 和 Skills（渐进式加载）
        
        MCP: 立即启动（需要进程通信）
        Skills: 只注册元数据，按需加载
        """
        from core.mcp_manager import MCPManager
        from core.skills_manager import SkillManager
        
        # 启动 MCP
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
                else:
                    print(f"❌ 启动 MCP 失败: {mcp_name}")
        
        # 渐进式加载 Skills - 只注册元数据
        skill_manager = SkillManager()
        
        for skill_name in self.config.mounted_skills:
            skill_config = skill_manager.get_skill(skill_name)
            if skill_config and skill_config.enabled:
                # 只注册元数据，不加载工具
                metadata = self.skill_loader.register_skill(skill_config.path)
                if metadata:
                    print(f"📋 注册 Skill: {skill_name}")
                    print(f"   描述: {metadata.description}")
                    print(f"   预估工具数: {metadata.tool_count}")
                    print(f"   状态: 等待按需加载")
        
        # 打印统计信息
        stats = self.skill_loader.get_stats()
        print(f"\n📊 Skills 加载统计:")
        print(f"   已注册: {stats['total_skills']} 个")
        print(f"   已加载: {stats['loaded_skills']} 个")
        print(f"   最大加载数: {stats['max_loaded']}")
    
    async def stop(self):
        """停止节点"""
        self._running = False
        
        if self.current_task:
            await self._release_task(self.current_task.id)
        
        for subnet_name in list(self.active_subnets.keys()):
            await self._destroy_subnet(subnet_name)
        
        # 停止所有 MCP 客户端
        await self.mcp_manager.stop_all()
        
        if self.llm_client:
            await self.llm_client.close()
        
        await self.p2p.stop()
        print(f"🧠 大脑节点 [{self.node_id}] 已下线")
    
    async def create_task(
        self,
        title: str,
        creator: str = "system",
        priority: int = 0,
        tags: List[str] = None,
        description: str = ""
    ) -> Task:
        """创建新任务"""
        task = self.crdt.create_task(
            title=title,
            creator=creator,
            priority=priority,
            tags=tags,
            description=description
        )
        
        await self._broadcast_crdt()
        await self._send_chat(f"📝 发布新任务: {title}", ref_task=task.id)
        
        print(f"📝 创建任务: {task.id} - {title}")
        return task
    
    async def delete_task(self, task_id: str) -> Tuple[bool, str]:
        """删除任务 - 只有创建者可以删除已完成的任务"""
        success, message = self.crdt.delete_task(task_id)
        
        if success:
            await self._broadcast_crdt()
            await self._send_chat(f"🗑️ 删除任务: {task_id}")
            print(f"🗑️ 删除任务: {task_id}")
        else:
            print(f"❌ 删除失败: {message}")
        
        return success, message
    
    def can_delete_task(self, task_id: str) -> Tuple[bool, str]:
        """检查是否可以删除任务"""
        return self.crdt.can_delete_task(task_id)
    
    async def send_chat(self, content: str, ref_task: str = None):
        """发送聊天消息"""
        message = ChatMessage(
            id=f"msg_{time.time_ns()}",
            sender=self.node_id,
            content=content,
            ref_task=ref_task
        )
        
        self.crdt.add_message(message)
        
        msg_data = {
            "type": MessageType.CHAT.value,
            "message": message.to_dict()
        }
        
        await self.p2p._publish(self.p2p.topic_crdt, msg_data)
        
        task_tag = f" [任务:{ref_task}]" if ref_task else ""
        print(f"💬 [我]{task_tag}: {content}")
    
    async def call_muscle(self, capability: str, arguments: Dict, timeout: float = 30.0) -> Any:
        """调用肌肉节点工具"""
        muscle_node = self.crdt.find_muscle(capability)
        
        if not muscle_node:
            raise ValueError(f"No available muscle node for: {capability}")
        
        request_id = f"req_{time.time_ns()}"
        
        request = {
            "request_id": request_id,
            "tool_name": capability,
            "arguments": arguments,
            "caller": self.node_id,
            "timestamp": time.time()
        }
        
        future = asyncio.Future()
        self._pending_tool_calls[request_id] = future
        
        await self.p2p.call_remote_tool(request)
        
        print(f"🔗 调用肌肉节点: {muscle_node} -> {capability}")
        
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            del self._pending_tool_calls[request_id]
            raise TimeoutError(f"Tool call timeout: {capability}")
    
    def register_task_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self._task_handlers[task_type] = handler
    
    async def _work_loop(self):
        """工作循环 - 抢占并执行任务"""
        while self._running:
            try:
                await self._try_work()
                await asyncio.sleep(self.config.work_interval)
            except Exception as e:
                print(f"❌ 工作循环错误: {e}")
                await asyncio.sleep(1)
    
    async def _try_work(self):
        """尝试抢占并执行任务"""
        if self.current_task:
            return
        
        pending_tasks = self.crdt.get_pending_tasks()
        
        for task in pending_tasks:
            subnet_topic = self.crdt.attempt_lock(task.id, self.config.lease_duration)
            
            if subnet_topic:
                self.current_task = self.crdt.tasks[task.id]
                self.state = BrainState.WORKING
                
                await self._broadcast_crdt()
                await self.send_chat(f"⚡ 我已接管任务，将在私有频道执行", ref_task=task.id)
                
                print(f"\n⚡ 抢占任务: {task.metadata.title}")
                print(f"   任务ID: {task.id}")
                print(f"   私有频道: {subnet_topic}")
                
                await self._create_subnet(subnet_topic)
                
                try:
                    await self._execute_task_in_subnet(task.id, subnet_topic)
                    
                    self.crdt.mark_done(task.id)
                    await self._broadcast_crdt()
                    
                    await self.send_chat(f"✅ 任务完成!", ref_task=task.id)
                    print(f"✅ 任务完成: {task.metadata.title}")
                    
                except Exception as e:
                    print(f"❌ 任务执行失败: {e}")
                    await self.send_chat(f"❌ 任务执行失败: {e}", ref_task=task.id)
                    await self._release_task(task.id)
                
                finally:
                    await self._destroy_subnet(subnet_topic)
                    self.current_task = None
                    self.state = BrainState.IDLE
                
                break
    
    async def _execute_task_in_subnet(self, task_id: str, subnet_topic: str):
        """在私有子网中执行任务"""
        task = self.crdt.tasks.get(task_id)
        if not task:
            return
        
        print(f"🔒 [私网] 开始执行任务...")
        
        self.crdt.confirm_progress(task_id, lease_extension=60)
        await self._broadcast_crdt()
        
        # 使用 TaskExecutor 执行（通过 MCP/Skills）
        result = await self.executor.execute(task)
        
        if result.get("success"):
            print(f"   ✅ 执行成功: {result.get('message', '完成')}")
            if result.get("result"):
                print(f"   📋 结果: {result['result'][:200]}...")
        else:
            error = result.get("error", "未知错误")
            print(f"   ❌ 执行失败: {error}")
            raise Exception(error)
    
    async def _create_subnet(self, subnet_topic: str):
        """创建私有子网"""
        if LIBB2P_AVAILABLE and self.p2p.pubsub:
            try:
                topic = await self.p2p.pubsub.subscribe(subnet_topic)
                self.active_subnets[subnet_topic] = topic
                print(f"🔒 创建私有子网: {subnet_topic}")
            except Exception as e:
                print(f"⚠️ 创建子网失败: {e}")
    
    async def _destroy_subnet(self, subnet_topic: str):
        """销毁私有子网"""
        if subnet_topic in self.active_subnets:
            try:
                if LIBB2P_AVAILABLE and self.p2p.pubsub:
                    await self.p2p.pubsub.unsubscribe(self.active_subnets[subnet_topic])
                del self.active_subnets[subnet_topic]
                print(f"🔓 销毁私有子网: {subnet_topic}")
            except Exception as e:
                print(f"⚠️ 销毁子网失败: {e}")
    
    async def _release_task(self, task_id: str):
        """释放任务"""
        if self.crdt.release_task(task_id):
            await self._broadcast_crdt()
            print(f"🔄 释放任务: {task_id}")
    
    async def _recovery_loop(self):
        """恢复循环 - 检测并恢复死节点任务"""
        while self._running:
            try:
                recovered = self.crdt.recover_expired_tasks(self.config.heartbeat_timeout)
                
                for task_id in recovered:
                    print(f"♻️ 恢复过期任务: {task_id}")
                    await self._broadcast_crdt()
                    await self.send_chat(f"♻️ 恢复过期任务: {task_id}")
                
                await asyncio.sleep(self.config.heartbeat_timeout)
            except Exception as e:
                print(f"❌ 恢复循环错误: {e}")
                await asyncio.sleep(5)
    
    async def _sync_with_server_loop(self):
        """与中心服务器同步"""
        if not self.config.server_url:
            return
        
        while self._running:
            try:
                await asyncio.sleep(10)
                all_tasks = self.crdt.get_all_tasks()
                for task_data in all_tasks.values():
                    await self._sync_to_server(task_data)
            except Exception as e:
                print(f"⚠️ 服务器同步错误: {e}")
    
    async def _sync_to_server(self, task_data: Dict):
        """同步到服务器"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.config.server_url}/sync",
                    json=task_data,
                    timeout=5.0
                )
        except:
            pass
    
    async def _broadcast_crdt(self):
        """广播CRDT状态"""
        all_tasks = self.crdt.get_all_tasks()
        message = {
            "type": MessageType.CRDT_SYNC.value,
            "node_id": self.node_id,
            "data": all_tasks,
            "timestamp": time.time()
        }
        await self.p2p._publish(self.p2p.topic_crdt, message)
    
    async def _send_chat(self, content: str, ref_task: str = None):
        """内部发送聊天"""
        await self.send_chat(content, ref_task)
    
    async def _handle_crdt_sync(self, message: Dict):
        """处理CRDT同步"""
        data = message.get("data", {})
        if data:
            count = self.crdt.merge_batch(data)
            if count > 0:
                print(f"🔄 CRDT同步: 合并 {count} 个任务")
    
    async def _handle_heartbeat(self, message: Dict):
        """处理心跳"""
        sender = message.get("node_id")
        self.crdt.update_heartbeat(sender)
    
    async def _handle_sync_request(self, message: Dict):
        """处理同步请求"""
        all_tasks = self.crdt.get_all_tasks()
        await self.p2p.send_full_sync(all_tasks)
    
    async def _handle_sync_full(self, message: Dict):
        """处理全量同步"""
        data = message.get("data", {})
        count = self.crdt.merge_batch(data)
        if count > 0:
            print(f"🔄 全量同步: 合并 {count} 个任务")
    
    async def _handle_muscle_announce(self, message: Dict):
        """处理肌肉节点公告"""
        node_id = message.get("node_id")
        capabilities = message.get("capabilities", [])
        
        self.crdt.register_muscle(node_id, capabilities)
        self.crdt.update_heartbeat(node_id)
        
        print(f"💪 发现肌肉节点: {node_id} -> {capabilities}")
    
    async def _handle_tool_response(self, message: Dict):
        """处理工具响应"""
        response = message.get("response", {})
        request_id = response.get("request_id")
        
        if request_id in self._pending_tool_calls:
            future = self._pending_tool_calls.pop(request_id)
            
            if response.get("success"):
                future.set_result(response.get("result"))
                print(f"✅ 工具调用成功: {request_id}")
            else:
                future.set_exception(Exception(response.get("error", "Unknown error")))
                print(f"❌ 工具调用失败: {request_id}")
    
    async def _handle_backup(self, message: Dict):
        """处理备份广播"""
        task_id = message.get("task_id")
        backup_data = message.get("backup_data")
        sender = message.get("node_id")
        
        print(f"📦 备份通知: {sender} -> {task_id}: {backup_data}")
    
    def get_status(self) -> Dict:
        """获取状态"""
        skill_stats = self.skill_loader.get_stats()
        remote_stats = self.remote_manager.get_stats() if self.remote_manager else {}
        
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "current_task": self.current_task.to_dict() if self.current_task else None,
            "stats": self.crdt.get_stats(),
            "active_subnets": list(self.active_subnets.keys()),
            "muscles_available": len(self.crdt.muscle_registry),
            "known_peers": self.p2p.get_known_peers(),
            "llm_configured": self.llm_client is not None,
            "mounted_mcps": self.config.mounted_mcps,
            "mounted_skills": self.config.mounted_skills,
            "active_mcps": list(self.mcp_manager.clients.keys()),
            "skill_stats": skill_stats,
            "remote_stats": remote_stats
        }
    
    def print_status(self):
        """打印状态"""
        stats = self.crdt.get_stats()
        skill_stats = self.skill_loader.get_stats()
        remote_stats = self.remote_manager.get_stats() if self.remote_manager else {}
        
        print(f"\n{'='*60}")
        print(f"🧠 大脑节点: {self.node_id}")
        print(f"   状态: {self.state.value}")
        print(f"   任务: {stats['total']} (待处理: {stats['pending']}, 执行中: {stats['in_progress']}, 完成: {stats['done']})")
        print(f"   可用肌肉节点: {stats['muscles_available']}")
        print(f"   活跃节点: {stats['alive_nodes']}")
        print(f"   活跃子网: {len(self.active_subnets)}")
        print(f"   LLM: {'已配置' if self.llm_client else '未配置'}")
        print(f"   活跃MCP: {list(self.mcp_manager.clients.keys())}")
        print(f"   Skills: {skill_stats['loaded_skills']}/{skill_stats['total_skills']} 已加载")
        print(f"   远程资源: Skills={remote_stats.get('remote_skills', 0)}, MCPs={remote_stats.get('remote_mcps', 0)}, Tools={remote_stats.get('remote_tools', 0)}")
        
        if self.current_task:
            print(f"   当前任务: {self.current_task.metadata.title}")
        
        print(f"{'='*60}\n")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Start a Brain Node")
    parser.add_argument("--name", required=True, help="Brain node name")
    parser.add_argument("--port", type=int, default=0, help="P2P port")
    parser.add_argument("--bootstrap", nargs="*", default=[], help="Bootstrap peers")
    parser.add_argument("--server", default="", help="Central server URL")
    parser.add_argument("--create-task", help="Create a task on startup")
    parser.add_argument("--llm-base-url", default="", help="LLM API base URL")
    parser.add_argument("--llm-api-key", default="", help="LLM API key")
    parser.add_argument("--llm-model", default="gpt-4", help="LLM model name")
    
    args = parser.parse_args()
    
    config = BrainConfig(
        name=args.name,
        port=args.port,
        bootstrap_peers=args.bootstrap,
        server_url=args.server,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        llm_model=args.llm_model
    )
    
    brain = BrainNode(config)
    
    try:
        await brain.start()
        
        if args.create_task:
            await asyncio.sleep(2)
            await brain.create_task(args.create_task)
        
        print("\n按 Ctrl+C 停止...")
        
        while True:
            await asyncio.sleep(10)
            brain.print_status()
            
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        await brain.stop()


if __name__ == "__main__":
    asyncio.run(main())
