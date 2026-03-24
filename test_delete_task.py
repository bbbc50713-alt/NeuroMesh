"""
测试任务删除功能 - 只有创建者可以删除已完成的任务
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.crdt_engine_v2 import EnhancedCRDTStore, TaskState


def test_delete_task():
    """测试任务删除功能"""
    print("\n" + "="*60)
    print("测试: 任务删除权限控制")
    print("="*60 + "\n")
    
    store_creator = EnhancedCRDTStore("Creator")
    store_other = EnhancedCRDTStore("Other")
    
    print("1. 创建者创建任务...")
    task = store_creator.create_task(
        title="测试任务",
        creator="Creator"
    )
    print(f"   创建: {task.id} - {task.metadata.title}")
    print(f"   创建者: {task.metadata.creator}")
    
    print("\n2. 尝试删除未完成的任务...")
    can_del, reason = store_creator.can_delete_task(task.id)
    print(f"   可以删除: {can_del}, 原因: {reason}")
    
    success, msg = store_creator.delete_task(task.id)
    print(f"   删除结果: {success}, 消息: {msg}")
    
    print("\n3. 模拟任务被抢占并完成...")
    subnet = store_creator.attempt_lock(task.id, lease_duration=10)
    print(f"   抢占成功: {subnet}")
    
    store_creator.mark_done(task.id)
    print(f"   任务状态: {store_creator.tasks[task.id].state}")
    
    print("\n4. 非创建者尝试删除...")
    task_data = store_creator.tasks[task.id].to_dict()
    store_other.merge_task(task_data)
    
    success, msg = store_other.delete_task(task.id)
    print(f"   删除结果: {success}, 消息: {msg}")
    
    print("\n5. 创建者删除已完成的任务...")
    success, msg = store_creator.delete_task(task.id)
    print(f"   删除结果: {success}, 消息: {msg}")
    
    print("\n6. 验证任务已被删除...")
    exists = task.id in store_creator.tasks
    print(f"   任务存在: {exists}")
    
    success = not exists and not store_other.delete_task(task.id)[0]
    
    print(f"\n{'✅' if success else '❌'} 删除权限测试{'通过' if success else '失败'}!")
    return success


async def test_delete_with_brain_nodes():
    """测试大脑节点间的删除功能"""
    print("\n" + "="*60)
    print("测试: 大脑节点删除功能")
    print("="*60 + "\n")
    
    from agent.brain_node import BrainNode, BrainConfig
    
    print("1. 创建两个大脑节点...")
    brain_creator = BrainNode(BrainConfig(name="Creator", port=10030))
    brain_other = BrainNode(BrainConfig(name="Other", port=10031))
    
    await brain_creator.start()
    await brain_other.start()
    
    await asyncio.sleep(1)
    
    print("\n2. Creator创建任务...")
    task = await brain_creator.create_task(
        title="测试删除任务",
        creator="Creator"
    )
    print(f"   任务ID: {task.id}")
    print(f"   创建者: {task.metadata.creator}")
    
    await asyncio.sleep(1)
    
    print("\n3. Creator抢占并完成任务...")
    subnet = brain_creator.crdt.attempt_lock(task.id, lease_duration=10)
    print(f"   抢占成功: {subnet}")
    
    brain_creator.crdt.mark_done(task.id)
    await brain_creator._broadcast_crdt()
    print(f"   任务状态: {brain_creator.crdt.tasks[task.id].state}")
    
    await asyncio.sleep(1)
    
    print("\n4. 同步到Other节点...")
    task_data = brain_creator.crdt.tasks[task.id].to_dict()
    brain_other.crdt.merge_task(task_data)
    print(f"   Other任务数: {len(brain_other.crdt.tasks)}")
    
    print("\n5. Other尝试删除（应该失败）...")
    success, msg = await brain_other.delete_task(task.id)
    print(f"   删除结果: {success}")
    print(f"   消息: {msg}")
    
    other_failed = not success
    
    print("\n6. Creator删除（应该成功）...")
    success, msg = await brain_creator.delete_task(task.id)
    print(f"   删除结果: {success}")
    print(f"   消息: {msg}")
    
    print("\n7. 验证删除结果...")
    exists_in_creator = task.id in brain_creator.crdt.tasks
    print(f"   Creator中任务存在: {exists_in_creator}")
    
    await asyncio.sleep(1)
    
    print("\n8. 清理...")
    await brain_creator.stop()
    await brain_other.stop()
    
    success = other_failed and success and not exists_in_creator
    
    print(f"\n{'✅' if success else '❌'} 大脑节点删除测试{'通过' if success else '失败'}!")
    return success


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "#"*60)
    print("# 任务删除权限测试套件")
    print("#"*60)
    
    results = {}
    
    print("\n" + "-"*60)
    print("测试1: CRDT层删除权限")
    print("-"*60)
    try:
        results["crdt_delete"] = test_delete_task()
    except Exception as e:
        print(f"❌ CRDT删除测试失败: {e}")
        results["crdt_delete"] = False
    
    await asyncio.sleep(1)
    
    print("\n" + "-"*60)
    print("测试2: 大脑节点删除权限")
    print("-"*60)
    try:
        results["brain_delete"] = await test_delete_with_brain_nodes()
    except Exception as e:
        print(f"❌ 大脑节点删除测试失败: {e}")
        results["brain_delete"] = False
    
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
