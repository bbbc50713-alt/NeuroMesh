"""
MVP测试脚本 - 验证多智能体协作

测试场景:
1. 两个Agent协作操作todolist
2. 任务抢占和完成
3. 备份广播机制
4. 失败恢复
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import Agent, AgentConfig


async def test_two_agents():
    """测试两个Agent协作"""
    print("\n" + "="*60)
    print("测试: 两个Agent协作操作TodoList")
    print("="*60 + "\n")
    
    config_a = AgentConfig(
        name="Agent-A",
        port=10000,
        lease_seconds=10
    )
    
    config_b = AgentConfig(
        name="Agent-B",
        port=10001,
        lease_seconds=10
    )
    
    agent_a = Agent(config_a)
    agent_b = Agent(config_b)
    
    try:
        print("启动 Agent-A...")
        peer_a = await agent_a.start()
        print(f"Agent-A Peer ID: {peer_a}")
        
        await asyncio.sleep(1)
        
        print("\n启动 Agent-B...")
        peer_b = await agent_b.start()
        print(f"Agent-B Peer ID: {peer_b}")
        
        await asyncio.sleep(2)
        
        print("\n" + "-"*60)
        print("Agent-A 创建任务...")
        print("-"*60)
        todo1 = await agent_a.create_todo("分析数据并生成报告")
        print(f"创建任务: {todo1.id} - {todo1.title}")
        
        await asyncio.sleep(3)
        
        print("\n" + "-"*60)
        print("Agent-B 创建任务...")
        print("-"*60)
        todo2 = await agent_b.create_todo("编写测试用例")
        print(f"创建任务: {todo2.id} - {todo2.title}")
        
        await asyncio.sleep(5)
        
        print("\n" + "-"*60)
        print("检查状态...")
        print("-"*60)
        agent_a.print_status()
        agent_b.print_status()
        
        print("\n" + "-"*60)
        print("等待任务执行...")
        print("-"*60)
        await asyncio.sleep(10)
        
        print("\n" + "-"*60)
        print("最终状态...")
        print("-"*60)
        agent_a.print_status()
        agent_b.print_status()
        
        stats_a = agent_a.crdt_store.get_stats()
        stats_b = agent_b.crdt_store.get_stats()
        
        print(f"\n验证结果:")
        print(f"  Agent-A todos: {stats_a['total']}")
        print(f"  Agent-B todos: {stats_b['total']}")
        print(f"  数据一致性: {'✓ 通过' if stats_a['total'] == stats_b['total'] else '✗ 失败'}")
        print(f"  已完成任务: {stats_a['done']}")
        
        return stats_a['total'] == stats_b['total']
        
    finally:
        await agent_a.stop()
        await agent_b.stop()


async def test_task_recovery():
    """测试任务恢复机制"""
    print("\n" + "="*60)
    print("测试: 任务恢复机制 (CRDT层面验证)")
    print("="*60 + "\n")
    
    from core.crdt_engine import CRDTStore
    
    store_a = CRDTStore("Agent-Primary")
    store_b = CRDTStore("Agent-Backup")
    
    print("1. 创建任务...")
    todo = store_a.create_todo("测试任务")
    print(f"   创建: {todo.id} - {todo.title}")
    
    print("\n2. Agent-A抢占任务...")
    locked = store_a.try_lock_task(todo.id, lease_seconds=2)
    print(f"   抢占结果: {locked}")
    
    todo_data = store_a.todos[todo.id].to_dict()
    
    print("\n3. 同步到Agent-B...")
    store_b.merge(todo_data)
    print(f"   Agent-B收到任务: {todo.id}")
    
    print("\n4. 模拟Agent-A心跳超时...")
    store_a.update_heartbeat("Agent-Primary")
    store_b.update_heartbeat("Agent-Backup")
    
    import time
    time.sleep(3)
    
    print("\n5. Agent-B尝试恢复任务...")
    store_b.update_heartbeat("Agent-Backup")
    
    recovered = store_b.recover_dead_tasks(timeout=1.0)
    print(f"   恢复的任务: {recovered}")
    
    if recovered:
        print("\n6. Agent-B抢占恢复的任务...")
        locked_b = store_b.try_lock_task(todo.id)
        print(f"   抢占结果: {locked_b}")
        
        if locked_b:
            store_b.complete_task(todo.id)
            print("   任务完成!")
    
    stats_b = store_b.get_stats()
    success = len(recovered) > 0 and stats_b['done'] > 0
    
    print(f"\n任务恢复测试: {'✓ 通过' if success else '✗ 失败'}")
    print(f"   恢复任务数: {len(recovered)}")
    print(f"   完成任务数: {stats_b['done']}")
    
    return success


async def test_mcp_tools():
    """测试MCP工具协议"""
    print("\n" + "="*60)
    print("测试: MCP工具协议")
    print("="*60 + "\n")
    
    config = AgentConfig(name="Agent-MCP", port=10004)
    agent = Agent(config)
    
    try:
        await agent.start()
        await asyncio.sleep(1)
        
        print("注册自定义工具...")
        
        async def custom_analyzer(args):
            return {"analysis": f"Analyzed: {args.get('data', 'unknown')}"}
        
        agent.register_tool(
            name="data_analyzer",
            description="Analyze data and return insights",
            handler=custom_analyzer,
            input_schema={
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Data to analyze"}
                }
            },
            tags=["analysis", "data"]
        )
        
        print("\n可用工具:")
        for tool in agent.mcp_registry.get_all_tools():
            print(f"  - {tool.name}: {tool.description}")
        
        print("\n调用工具...")
        result = await agent.call_tool("data_analyzer", {"data": "test_data"})
        print(f"结果: {result}")
        
        print("\nMCP工具测试: ✓ 通过")
        return True
        
    finally:
        await agent.stop()


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "#"*60)
    print("# Agent P2P MVP 测试套件")
    print("#"*60)
    
    results = {}
    
    try:
        results["two_agents"] = await test_two_agents()
    except Exception as e:
        print(f"两Agent测试失败: {e}")
        results["two_agents"] = False
    
    await asyncio.sleep(2)
    
    try:
        results["task_recovery"] = await test_task_recovery()
    except Exception as e:
        print(f"任务恢复测试失败: {e}")
        results["task_recovery"] = False
    
    await asyncio.sleep(2)
    
    try:
        results["mcp_tools"] = await test_mcp_tools()
    except Exception as e:
        print(f"MCP工具测试失败: {e}")
        results["mcp_tools"] = False
    
    print("\n" + "#"*60)
    print("# 测试结果汇总")
    print("#"*60)
    
    for test_name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    print(f"\n总体结果: {'✓ 全部通过' if all_passed else '✗ 部分失败'}")
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(run_all_tests())
