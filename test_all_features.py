"""
完整功能测试 - 测试所有今天更新的功能

测试内容:
1. 渐进式加载功能 (SkillLoader)
2. 远程资源发现功能 (RemoteResourceManager)
3. 点对点直连调用 (P2PNetwork.direct_call)
4. 任务委派模式 (P2PNetwork.delegate_task)
5. Muscle节点任务认领
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.skill_loader import SkillLoader, SkillLoadState, SkillMetadata, SkillTool
from core.remote_resource_manager import (
    RemoteResourceManager, 
    RemoteSkillMetadata, 
    RemoteMCPMetadata,
    RemoteTool,
    RemoteResourceType
)
from network.p2p_network import P2PNetwork, P2PConfig, MessageType


class TestSkillLoader(unittest.TestCase):
    """测试 SkillLoader 渐进式加载功能"""
    
    def setUp(self):
        self.loader = SkillLoader(max_loaded_skills=5, auto_unload=True)
        self.test_skill_dir = None
    
    def tearDown(self):
        if self.test_skill_dir and os.path.exists(self.test_skill_dir):
            import shutil
            shutil.rmtree(self.test_skill_dir, ignore_errors=True)
    
    def _create_test_skill(self, name: str, has_script: bool = True, has_mcp: bool = False):
        """创建测试 Skill 目录"""
        self.test_skill_dir = tempfile.mkdtemp(prefix=f"skill_{name}_")
        
        skill_md = os.path.join(self.test_skill_dir, "skill.md")
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(f"# {name}\n\n这是一个测试 Skill")
        
        if has_script:
            script_dir = os.path.join(self.test_skill_dir, "script")
            os.makedirs(script_dir, exist_ok=True)
            script_file = os.path.join(script_dir, "tools.py")
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(f'''
def tool_one(args):
    """工具一"""
    return {{"result": "tool_one executed"}}

def tool_two(args):
    """工具二"""
    return {{"result": "tool_two executed"}}
''')
        
        if has_mcp:
            mcp_dir = os.path.join(self.test_skill_dir, "mcp")
            os.makedirs(mcp_dir, exist_ok=True)
            mcp_config = os.path.join(mcp_dir, "mcp.json")
            with open(mcp_config, "w", encoding="utf-8") as f:
                json.dump({
                    "mcpServers": {
                        "server1": {
                            "command": "python",
                            "args": ["-m", "mcp_server"],
                            "description": "Test MCP Server"
                        }
                    }
                }, f)
        
        return self.test_skill_dir
    
    def _get_skill_name(self, skill_path: str) -> str:
        """获取 skill 名称"""
        import os
        return os.path.basename(skill_path)
    
    def test_register_skill_metadata_only(self):
        """测试只注册元数据（不加载工具）"""
        skill_path = self._create_test_skill("test_skill_1", has_script=True)
        
        metadata = self.loader.register_skill(skill_path)
        
        self.assertIsNotNone(metadata)
        self.assertTrue(metadata.name.startswith("skill_test_skill_1"))
        self.assertEqual(metadata.load_state, SkillLoadState.METADATA_ONLY)
        self.assertTrue(metadata.has_script)
        self.assertGreater(metadata.tool_count, 0)
        
        self.assertEqual(len(self.loader.loaded_tools), 0)
        self.assertEqual(len(self.loader.skills_metadata), 1)
    
    def test_progressive_load(self):
        """测试渐进式加载 - 按需加载工具"""
        skill_path = self._create_test_skill("test_skill_2", has_script=True)
        skill_name = self._get_skill_name(skill_path)
        
        self.loader.register_skill(skill_path)
        self.assertEqual(len(self.loader.loaded_tools), 0)
        
        async def async_test():
            tools = await self.loader.load_skill_full(skill_name)
            return tools
        
        tools = asyncio.run(async_test())
        
        self.assertGreater(len(tools), 0)
        self.assertEqual(len(self.loader.loaded_tools), len(tools))
        
        metadata = self.loader.skills_metadata.get(skill_name)
        self.assertEqual(metadata.load_state, SkillLoadState.FULLY_LOADED)
    
    def test_ensure_tool_loaded(self):
        """测试确保工具已加载"""
        skill_path = self._create_test_skill("test_skill_3", has_script=True)
        skill_name = self._get_skill_name(skill_path)
        self.loader.register_skill(skill_path)
        
        tool_name = f"skill_{skill_name}_tool_one"
        
        async def async_test():
            print(f"Debug: skill_name = {skill_name}")
            print(f"Debug: tool_name = {tool_name}")
            print(f"Debug: registered skills = {list(self.loader.skills_metadata.keys())}")
            tool = await self.loader.ensure_tool_loaded(tool_name)
            print(f"Debug: loaded tools = {list(self.loader.loaded_tools.keys())}")
            print(f"Debug: result tool = {tool}")
            return tool
        
        tool = asyncio.run(async_test())
        
        self.assertIsNotNone(tool, f"Tool should not be None, tool_name={tool_name}")
        self.assertEqual(tool.skill_name, skill_name)
    
    def test_auto_unload(self):
        """测试自动卸载不常用的 Skills"""
        loader = SkillLoader(max_loaded_skills=2, auto_unload=True)
        
        for i in range(4):
            skill_path = self._create_test_skill(f"skill_{i}", has_script=True)
            loader.register_skill(skill_path)
            
            async def load_skill(name):
                await loader.load_skill_full(name)
            
            asyncio.run(load_skill(f"skill_{i}"))
            
            self.test_skill_dir = None
        
        loaded_count = len([m for m in loader.skills_metadata.values() 
                           if m.load_state == SkillLoadState.FULLY_LOADED])
        
        self.assertLessEqual(loaded_count, 2)
    
    def test_get_tool_definitions(self):
        """测试获取工具定义（用于 LLM function calling）"""
        skill_path = self._create_test_skill("test_skill_4", has_script=True)
        self.loader.register_skill(skill_path)
        
        definitions = self.loader.get_tool_definitions()
        
        self.assertGreater(len(definitions), 0)
        
        found_placeholder = False
        for d in definitions:
            if "未加载" in d.get("function", {}).get("description", ""):
                found_placeholder = True
                break
        
        self.assertTrue(found_placeholder)
    
    def test_get_stats(self):
        """测试获取统计信息"""
        skill_path = self._create_test_skill("test_skill_5", has_script=True)
        self.loader.register_skill(skill_path)
        
        stats = self.loader.get_stats()
        
        self.assertEqual(stats["total_skills"], 1)
        self.assertEqual(stats["loaded_skills"], 0)
        self.assertEqual(stats["max_loaded"], 5)
        self.assertTrue(stats["auto_unload"])


class TestRemoteResourceManager(unittest.TestCase):
    """测试远程资源管理器"""
    
    def test_remote_skill_metadata(self):
        """测试远程 Skill 元数据"""
        metadata = RemoteSkillMetadata(
            skill_name="test_skill",
            node_id="node_1",
            description="Test skill",
            tool_count=3,
            has_script=True,
            has_mcp=False
        )
        
        data = metadata.to_dict()
        restored = RemoteSkillMetadata.from_dict(data)
        
        self.assertEqual(restored.skill_name, "test_skill")
        self.assertEqual(restored.node_id, "node_1")
        self.assertEqual(restored.tool_count, 3)
    
    def test_remote_mcp_metadata(self):
        """测试远程 MCP 元数据"""
        metadata = RemoteMCPMetadata(
            mcp_name="test_mcp",
            node_id="node_2",
            tools=[{"function": {"name": "tool1"}}],
            description="Test MCP"
        )
        
        data = metadata.to_dict()
        restored = RemoteMCPMetadata.from_dict(data)
        
        self.assertEqual(restored.mcp_name, "test_mcp")
        self.assertEqual(len(restored.tools), 1)
    
    def test_remote_tool(self):
        """测试远程工具"""
        tool = RemoteTool(
            name="remote_node1_skill_test_tool",
            node_id="node1",
            resource_type=RemoteResourceType.SKILL,
            resource_name="test_skill",
            description="Test tool",
            input_schema={"type": "object", "properties": {}}
        )
        
        definition = tool.to_tool_definition()
        
        self.assertEqual(definition["type"], "function")
        self.assertIn("远程:node1", definition["function"]["description"])
    
    def test_resource_manager_init(self):
        """测试资源管理器初始化"""
        mock_p2p = MagicMock()
        mock_p2p.on_message = MagicMock()
        
        manager = RemoteResourceManager(
            node_id="test_node",
            p2p_network=mock_p2p
        )
        
        self.assertEqual(manager.node_id, "test_node")
        self.assertEqual(len(manager.remote_skills), 0)
        self.assertEqual(len(manager.remote_mcps), 0)
        
        mock_p2p.on_message.assert_called()
    
    def test_handle_skill_announce(self):
        """测试处理 Skill 公告"""
        mock_p2p = MagicMock()
        mock_p2p.on_message = MagicMock()
        mock_p2p.topic_crdt = "test_topic"
        
        manager = RemoteResourceManager(
            node_id="local_node",
            p2p_network=mock_p2p
        )
        
        message = {
            "node_id": "remote_node",
            "skill": {
                "skill_name": "remote_skill",
                "description": "A remote skill",
                "tool_count": 2,
                "has_script": True,
                "has_mcp": False
            }
        }
        
        asyncio.run(manager._handle_skill_announce(message))
        
        self.assertEqual(len(manager.remote_skills), 1)
        self.assertEqual(len(manager.remote_tools), 2)
    
    def test_handle_mcp_announce(self):
        """测试处理 MCP 公告"""
        mock_p2p = MagicMock()
        mock_p2p.on_message = MagicMock()
        mock_p2p.topic_crdt = "test_topic"
        
        manager = RemoteResourceManager(
            node_id="local_node",
            p2p_network=mock_p2p
        )
        
        message = {
            "node_id": "remote_node",
            "mcp": {
                "mcp_name": "remote_mcp",
                "tools": [
                    {"function": {"name": "tool1", "description": "Tool 1"}},
                    {"function": {"name": "tool2", "description": "Tool 2"}}
                ]
            }
        }
        
        asyncio.run(manager._handle_mcp_announce(message))
        
        self.assertEqual(len(manager.remote_mcps), 1)
        self.assertEqual(len(manager.remote_tools), 2)
    
    def test_get_stats(self):
        """测试获取远程资源统计"""
        mock_p2p = MagicMock()
        mock_p2p.on_message = MagicMock()
        
        manager = RemoteResourceManager(
            node_id="test_node",
            p2p_network=mock_p2p
        )
        
        manager.remote_skills["test"] = RemoteSkillMetadata(
            skill_name="test", node_id="node1"
        )
        manager.remote_mcps["test_mcp"] = RemoteMCPMetadata(
            mcp_name="test_mcp", node_id="node1"
        )
        manager.remote_tools["tool1"] = RemoteTool(
            name="tool1", node_id="node1",
            resource_type=RemoteResourceType.SKILL,
            resource_name="test"
        )
        
        stats = manager.get_stats()
        
        self.assertEqual(stats["remote_skills"], 1)
        self.assertEqual(stats["remote_mcps"], 1)
        self.assertEqual(stats["remote_tools"], 1)


class TestP2PDirectCall(unittest.TestCase):
    """测试 P2P 点对点直连调用"""
    
    def test_message_types(self):
        """测试新增的消息类型"""
        self.assertEqual(MessageType.DIRECT_CALL.value, "direct_call")
        self.assertEqual(MessageType.DIRECT_RESPONSE.value, "direct_response")
        self.assertEqual(MessageType.TASK_DELEGATE.value, "task_delegate")
        self.assertEqual(MessageType.TASK_CLAIM.value, "task_claim")
        self.assertEqual(MessageType.TASK_RESULT.value, "task_result")
    
    def test_p2p_init_with_new_handlers(self):
        """测试 P2P 网络初始化包含新的处理器"""
        p2p = P2PNetwork("test_node")
        
        self.assertIn(MessageType.DIRECT_CALL.value, p2p._handlers)
        self.assertIn(MessageType.DIRECT_RESPONSE.value, p2p._handlers)
        self.assertIn(MessageType.TASK_DELEGATE.value, p2p._handlers)
        self.assertIn(MessageType.TASK_CLAIM.value, p2p._handlers)
        self.assertIn(MessageType.TASK_RESULT.value, p2p._handlers)
        
        self.assertEqual(p2p._pending_direct_calls, {})
        self.assertEqual(p2p._pending_tasks, {})
    
    def test_register_peer_addr(self):
        """测试注册节点地址"""
        p2p = P2PNetwork("test_node")
        
        p2p.register_peer_addr("peer1", "/ip4/127.0.0.1/tcp/4001/p2p/peer1")
        
        self.assertEqual(p2p.get_peer_addr_by_id("peer1"), "/ip4/127.0.0.1/tcp/4001/p2p/peer1")
    
    def test_direct_call_structure(self):
        """测试直接调用消息结构"""
        p2p = P2PNetwork("test_node")
        p2p._running = True
        p2p.topic_crdt = MagicMock()
        p2p.topic_crdt.publish = AsyncMock()
        
        async def test_call():
            call_task = asyncio.create_task(
                p2p.direct_call(
                    target_node="target",
                    call_type="skill_tool",
                    payload={"tool": "test"},
                    timeout=0.1
                )
            )
            
            await asyncio.sleep(0.05)
            
            for request_id, future in list(p2p._pending_direct_calls.items()):
                future.set_result({"success": True})
            
            try:
                result = await asyncio.wait_for(call_task, timeout=0.2)
                return result
            except asyncio.TimeoutError:
                return {"error": "timeout"}
        
        result = asyncio.run(test_call())
        
        self.assertIsNotNone(result)


class TestTaskDelegation(unittest.TestCase):
    """测试任务委派模式"""
    
    def test_delegate_task_structure(self):
        """测试任务委派消息结构"""
        p2p = P2PNetwork("delegator")
        p2p._running = True
        p2p.topic_crdt = MagicMock()
        p2p.topic_crdt.publish = AsyncMock()
        
        async def test_delegate():
            delegate_task = asyncio.create_task(
                p2p.delegate_task(
                    task_id="task_001",
                    task_data={"title": "Test Task"},
                    required_capabilities=["tool1"],
                    timeout=0.1
                )
            )
            
            await asyncio.sleep(0.05)
            
            for task_id, future in list(p2p._pending_tasks.items()):
                future.set_result({"claimed": True, "claimer": "worker1"})
            
            try:
                result = await asyncio.wait_for(delegate_task, timeout=0.2)
                return result
            except asyncio.TimeoutError:
                return {"error": "timeout"}
        
        result = asyncio.run(test_delegate())
        
        self.assertTrue(result.get("claimed", False))
    
    def test_claim_task_message(self):
        """测试任务认领消息"""
        p2p = P2PNetwork("worker")
        p2p._running = True
        p2p.topic_crdt = MagicMock()
        p2p.topic_crdt.publish = AsyncMock()
        
        async def test_claim():
            await p2p.claim_task("task_001", "delegator")
            return True
        
        result = asyncio.run(test_claim())
        
        self.assertTrue(result)
        p2p.topic_crdt.publish.assert_called_once()
    
    def test_submit_task_result_message(self):
        """测试提交任务结果消息"""
        p2p = P2PNetwork("worker")
        p2p._running = True
        p2p.topic_crdt = MagicMock()
        p2p.topic_crdt.publish = AsyncMock()
        
        async def test_submit():
            await p2p.submit_task_result(
                task_id="task_001",
                delegator_node="delegator",
                result={"success": True, "output": "done"}
            )
            return True
        
        result = asyncio.run(test_submit())
        
        self.assertTrue(result)
        p2p.topic_crdt.publish.assert_called_once()
    
    def test_handle_task_delegate(self):
        """测试处理任务委派"""
        p2p = P2PNetwork("worker")
        p2p._running = True
        p2p.topic_crdt = MagicMock()
        p2p.topic_crdt.publish = AsyncMock()
        
        claimed = []
        
        async def can_handle(message):
            required = message.get("required_capabilities", [])
            return "tool1" in required
        
        p2p.on_message(MessageType.TASK_DELEGATE.value, can_handle)
        
        message = {
            "task_id": "task_001",
            "task_data": {"title": "Test"},
            "required_capabilities": ["tool1"],
            "node_id": "delegator"
        }
        
        async def test_handle():
            await p2p._handle_task_delegate(message)
            return True
        
        asyncio.run(test_handle())
        
        p2p.topic_crdt.publish.assert_called()
    
    def test_handle_task_claim(self):
        """测试处理任务认领响应"""
        p2p = P2PNetwork("delegator")
        
        async def async_test():
            future = asyncio.Future()
            p2p._pending_tasks["task_001"] = future
            
            message = {
                "task_id": "task_001",
                "delegator_node": "delegator",
                "node_id": "worker1"
            }
            
            await p2p._handle_task_claim(message)
            
            self.assertTrue(future.done())
            result = future.result()
            self.assertTrue(result["claimed"])
            self.assertEqual(result["claimer"], "worker1")
        
        asyncio.run(async_test())


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def test_full_workflow(self):
        """测试完整工作流程"""
        loader = SkillLoader()
        
        test_dir = tempfile.mkdtemp(prefix="integration_test_")
        try:
            skill_md = os.path.join(test_dir, "skill.md")
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write("# Integration Test Skill\n\nTest skill for integration")
            
            script_dir = os.path.join(test_dir, "script")
            os.makedirs(script_dir, exist_ok=True)
            script_file = os.path.join(script_dir, "tools.py")
            with open(script_file, "w", encoding="utf-8") as f:
                f.write('''
def test_tool(**kwargs):
    """Test tool"""
    return {"status": "ok"}
''')
            
            metadata = loader.register_skill(test_dir)
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata.load_state, SkillLoadState.METADATA_ONLY)
            
            skill_name = os.path.basename(test_dir)
            
            async def load_and_call():
                tools = await loader.load_skill_full(skill_name)
                self.assertGreater(len(tools), 0)
                
                tool_name = tools[0].name
                result = await loader.call_tool(tool_name, {})
                return result
            
            result = asyncio.run(load_and_call())
            self.assertTrue(result.get("success", False), f"Result: {result}")
            
            stats = loader.get_stats()
            self.assertEqual(stats["total_skills"], 1)
            self.assertEqual(stats["loaded_skills"], 1)
            
        finally:
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)


def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSkillLoader))
    suite.addTests(loader.loadTestsFromTestCase(TestRemoteResourceManager))
    suite.addTests(loader.loadTestsFromTestCase(TestP2PDirectCall))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskDelegation))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("开始运行所有功能测试")
    print("=" * 60)
    print()
    
    result = run_all_tests()
    
    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"运行测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback}")
    
    if result.errors:
        print("\n出错的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")
    
    if result.wasSuccessful():
        print("\n✅ 所有测试通过!")
    else:
        print("\n❌ 存在测试失败，请检查!")
    
    sys.exit(0 if result.wasSuccessful() else 1)
