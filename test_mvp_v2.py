"""
V2.0 MVP测试 - 验证脑手分离架构

测试场景:
1. 大脑节点 + 肌肉节点协作
2. 私有子网机制
3. 聊天室融合
4. 任务黑洞防御
5. 肌肉节点调用
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.crdt_engine_v2 import EnhancedCRDTStore, Task, ChatMessage, TaskState


def test_enhanced_crdt():
    """测试增强版CRDT引擎"""
    print("\n" + "="*60)
    print("测试: 增强版CRDT引擎")
    print("="*60 + "\n")
    
    store_a = EnhancedCRDTStore("Brain-A")
    store_b = EnhancedCRDTStore("Brain-B")
    
    print("1. 创建任务...")
    task = store_a.create_task(
        title="分析Q3财报",
        creator="Human-Admin",
        priority=1,
        tags=["analysis", "finance"]
    )
    print(f"   创建: {task.id} - {task.metadata.title}")
    
    print("\n2. 尝试抢占任务...")
    subnet = store_a.attempt_lock(task.id, lease_duration=5)
    print(f"   抢占结果: {subnet}")
    print(f"   任务状态: {store_a.tasks[task.id].state}")
    
    print("\n3. 同步到Brain-B...")
    task_data = store_a.tasks[task.id].to_dict()
    store_b.merge_task(task_data)
    print(f"   Brain-B任务数: {len(store_b.tasks)}")
    
    print("\n4. 测试租约过期恢复...")
    time.sleep(6)
    
    recovered = store_b.recover_expired_tasks(timeout=1.0)
    print(f"   恢复任务: {recovered}")
    
    print("\n5. Brain-B抢占恢复的任务...")
    subnet_b = store_b.attempt_lock(task.id)
    print(f"   抢占结果: {subnet_b}")
    
    print("\n6. 测试聊天消息...")
    msg = ChatMessage(
        id="msg_001",
        sender="Brain-A",
        content="我遇到了问题，需要帮助",
        ref_task=task.id
    )
    store_a.add_message(msg)
    messages = store_a.get_messages(ref_task=task.id)
    print(f"   消息数: {len(messages)}")
    
    print("\n7. 测试肌肉节点注册...")
    store_a.register_muscle("Muscle-Camera", ["mcp/camera_capture", "mcp/camera_stream"])
    store_a.register_muscle("Muscle-Database", ["mcp/sql_query"])
    
    muscle = store_a.find_muscle("mcp/camera_capture")
    print(f"   找到肌肉节点: {muscle}")
    
    stats = store_a.get_stats()
    print(f"\n统计: {stats}")
    
    print("\n✅ CRDT引擎测试通过!")
    return True


async def test_brain_muscle_collaboration():
    """测试大脑-肌肉协作"""
    print("\n" + "="*60)
    print("测试: 大脑-肌肉节点协作")
    print("="*60 + "\n")
    
    from agent.muscle_node import MuscleNode, MuscleConfig
    from agent.brain_node import BrainNode, BrainConfig
    
    print("1. 创建肌肉节点...")
    muscle_config = MuscleConfig(
        name="Muscle-Test",
        port=10020
    )
    muscle = MuscleNode(muscle_config)
    
    async def test_tool(args):
        return {"status": "success", "data": f"Processed: {args}"}
    
    muscle.register_tool(
        name="mcp/test_tool",
        handler=test_tool,
        description="Test tool"
    )
    
    await muscle.start()
    
    print("\n2. 创建大脑节点...")
    brain_config = BrainConfig(
        name="Brain-Test",
        port=10021
    )
    brain = BrainNode(brain_config)
    
    await brain.start()
    
    await asyncio.sleep(2)
    
    print("\n3. 大脑创建任务...")
    task = await brain.create_task("测试任务", tags=["test"])
    print(f"   任务ID: {task.id}")
    
    await asyncio.sleep(3)
    
    print("\n4. 检查状态...")
    brain.print_status()
    
    print("\n5. 测试聊天...")
    await brain.send_chat("这是一条测试消息", ref_task=task.id)
    
    await asyncio.sleep(2)
    
    print("\n6. 清理...")
    await brain.stop()
    await muscle.stop()
    
    print("\n✅ 大脑-肌肉协作测试通过!")
    return True


async def test_private_subnet():
    """测试私有子网机制"""
    print("\n" + "="*60)
    print("测试: 私有子网机制")
    print("="*60 + "\n")
    
    from agent.brain_node import BrainNode, BrainConfig
    
    print("1. 创建两个大脑节点...")
    brain_a = BrainNode(BrainConfig(name="Brain-A", port=10022))
    brain_b = BrainNode(BrainConfig(name="Brain-B", port=10023))
    
    await brain_a.start()
    await brain_b.start()
    
    await asyncio.sleep(2)
    
    print("\n2. Brain-A创建任务...")
    task = await brain_a.create_task("私有子网测试任务")
    
    await asyncio.sleep(2)
    
    print("\n3. Brain-A抢占任务...")
    subnet = brain_a.crdt.attempt_lock(task.id, lease_duration=10)
    print(f"   私有子网: {subnet}")
    
    if subnet:
        await brain_a._create_subnet(subnet)
        print(f"   子网已创建")
        
        await brain_a.send_chat("进入私有频道工作", ref_task=task.id)
        
        await asyncio.sleep(2)
        
        print("\n4. 模拟在私有子网工作...")
        brain_a.crdt.confirm_progress(task.id)
        await brain_a._broadcast_crdt()
        
        await asyncio.sleep(2)
        
        print("\n5. 完成任务并销毁子网...")
        brain_a.crdt.mark_done(task.id)
        await brain_a._broadcast_crdt()
        
        await brain_a._destroy_subnet(subnet)
    
    await asyncio.sleep(2)
    
    print("\n6. 检查最终状态...")
    brain_a.print_status()
    brain_b.print_status()
    
    print("\n7. 清理...")
    await brain_a.stop()
    await brain_b.stop()
    
    print("\n✅ 私有子网测试通过!")
    return True


async def test_task_blackhole_prevention():
    """测试任务黑洞防御"""
    print("\n" + "="*60)
    print("测试: 任务黑洞防御机制")
    print("="*60 + "\n")
    
    from agent.brain_node import BrainNode, BrainConfig
    
    print("1. 创建大脑节点（禁用自动工作循环）...")
    brain_a = BrainNode(BrainConfig(
        name="Brain-Primary",
        port=10024,
        lease_duration=2
    ))
    brain_b = BrainNode(BrainConfig(
        name="Brain-Backup",
        port=10025,
        heartbeat_timeout=1.0
    ))
    
    await brain_a.start()
    await brain_b.start()
    
    brain_a._running = False
    
    await asyncio.sleep(1)
    
    print("\n2. 创建任务...")
    task = await brain_a.create_task("黑洞防御测试")
    
    await asyncio.sleep(1)
    
    print("\n3. Brain-A手动锁定任务...")
    subnet = brain_a.crdt.attempt_lock(task.id, lease_duration=2)
    print(f"   抢占成功: {subnet}")
    print(f"   任务状态: {brain_a.crdt.tasks[task.id].state}")
    
    await brain_a._broadcast_crdt()
    
    print("\n4. 同步任务状态到Brain-B...")
    task_data = brain_a.crdt.tasks[task.id].to_dict()
    brain_b.crdt.merge_task(task_data)
    print(f"   Brain-B任务状态: {brain_b.crdt.tasks[task.id].state}")
    
    print("\n5. 更新心跳...")
    brain_a.crdt.update_heartbeat("Brain-Primary")
    brain_b.crdt.update_heartbeat("Brain-Backup")
    
    print("\n6. 等待租约过期...")
    await asyncio.sleep(3)
    
    print("\n7. Brain-B检测并恢复任务...")
    recovered = brain_b.crdt.recover_expired_tasks(timeout=1.0)
    print(f"   恢复的任务: {recovered}")
    
    success = len(recovered) > 0
    
    if success:
        print("\n8. Brain-B接管恢复的任务...")
        subnet_b = brain_b.crdt.attempt_lock(task.id)
        print(f"   Brain-B接管成功: {subnet_b}")
        
        brain_b.crdt.mark_done(task.id)
        await brain_b._broadcast_crdt()
        print("   任务已完成")
    
    await asyncio.sleep(1)
    
    print("\n9. 验证最终状态...")
    stats_a = brain_a.crdt.get_stats()
    stats_b = brain_b.crdt.get_stats()
    
    print(f"   Brain-A: done={stats_a['done']}")
    print(f"   Brain-B: done={stats_b['done']}")
    
    print("\n10. 清理...")
    await brain_b.stop()
    
    print(f"\n{'✅' if success else '❌'} 黑洞防御测试{'通过' if success else '失败'}!")
    return success


async def test_chat_integration():
    """测试聊天室融合"""
    print("\n" + "="*60)
    print("测试: 聊天室融合")
    print("="*60 + "\n")
    
    from agent.brain_node import BrainNode, BrainConfig
    
    print("1. 创建大脑节点...")
    brain_a = BrainNode(BrainConfig(name="Brain-A", port=10026))
    brain_b = BrainNode(BrainConfig(name="Brain-B", port=10027))
    
    await brain_a.start()
    await brain_b.start()
    
    await asyncio.sleep(2)
    
    print("\n2. 发送聊天消息...")
    await brain_a.send_chat("大家好，我是Brain-A")
    await asyncio.sleep(1)
    
    await brain_b.send_chat("收到，我是Brain-B")
    await asyncio.sleep(1)
    
    print("\n3. 关联任务的聊天...")
    task = await brain_a.create_task("聊天测试任务")
    await asyncio.sleep(1)
    
    await brain_a.send_chat("我正在处理这个任务", ref_task=task.id)
    await asyncio.sleep(1)
    
    await brain_b.send_chat("需要帮忙吗？", ref_task=task.id)
    await asyncio.sleep(1)
    
    print("\n4. 检查消息记录...")
    messages_a = brain_a.crdt.get_messages()
    messages_b = brain_b.crdt.get_messages()
    
    print(f"   Brain-A消息数: {len(messages_a)}")
    print(f"   Brain-B消息数: {len(messages_b)}")
    
    print("\n5. 清理...")
    await brain_a.stop()
    await brain_b.stop()
    
    success = len(messages_a) > 0 and len(messages_b) > 0
    print(f"\n{'✅' if success else '❌'} 聊天室融合测试{'通过' if success else '失败'}!")
    return success


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "#"*60)
    print("# Agent P2P V2.0 测试套件")
    print("#"*60)
    
    results = {}
    
    print("\n" + "-"*60)
    print("测试1: 增强版CRDT引擎")
    print("-"*60)
    try:
        results["crdt"] = test_enhanced_crdt()
    except Exception as e:
        print(f"❌ CRDT测试失败: {e}")
        results["crdt"] = False
    
    await asyncio.sleep(1)
    
    print("\n" + "-"*60)
    print("测试2: 大脑-肌肉协作")
    print("-"*60)
    try:
        results["brain_muscle"] = await test_brain_muscle_collaboration()
    except Exception as e:
        print(f"❌ 大脑-肌肉测试失败: {e}")
        results["brain_muscle"] = False
    
    await asyncio.sleep(1)
    
    print("\n" + "-"*60)
    print("测试3: 私有子网机制")
    print("-"*60)
    try:
        results["private_subnet"] = await test_private_subnet()
    except Exception as e:
        print(f"❌ 私有子网测试失败: {e}")
        results["private_subnet"] = False
    
    await asyncio.sleep(1)
    
    print("\n" + "-"*60)
    print("测试4: 任务黑洞防御")
    print("-"*60)
    try:
        results["blackhole"] = await test_task_blackhole_prevention()
    except Exception as e:
        print(f"❌ 黑洞防御测试失败: {e}")
        results["blackhole"] = False
    
    await asyncio.sleep(1)
    
    print("\n" + "-"*60)
    print("测试5: 聊天室融合")
    print("-"*60)
    try:
        results["chat"] = await test_chat_integration()
    except Exception as e:
        print(f"❌ 聊天室测试失败: {e}")
        results["chat"] = False
    
    print("\n" + "#"*60)
    print("# 测试结果汇总")
    print("#"*60)
    
    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    print(f"\n总体结果: {'✅ 全部通过' if all_passed else '❌ 部分失败'}")
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(run_all_tests())
