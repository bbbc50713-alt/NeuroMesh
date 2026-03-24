"""
终端UI界面 - 用于管理和监控Agent P2P网络

功能:
1. 挂载Agents - 查看在线节点
2. 挂载Skills - 查看可用技能
3. 挂载MCP工具 - 查看可用工具
4. 确认上链 - 测试网络连接
5. 链上资源 - 查看资源状态
6. 链上智能体协作 - 查看协作状态
7. Todolist管理 - 创建、查看、删除任务
"""

import asyncio
import sys
import os
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.brain_node import BrainNode, BrainConfig
from agent.muscle_node import MuscleNode, MuscleConfig
from core.crdt_engine_v2 import EnhancedCRDTStore, TaskState


class TerminalUI:
    """终端UI管理器"""
    
    def __init__(self):
        self.agents: Dict[str, BrainNode] = {}
        self.muscles: Dict[str, MuscleNode] = {}
        self.running = False
        self._tasks: Dict[str, dict] = {}
    
    async def start(self):
        """启动UI"""
        self.running = True
        print("\n" + "="*60)
        print("🚀 Agent P2P 终端UI")
        print("="*60 + "\n")
        print("命令帮助:")
        print("  help              - 显示帮助")
        print("  list agents      - 列出所有Agent")
        print("  list muscles     - 列出所有Muscle节点")
        print("  list tasks       - 列出所有任务")
        print("  create <title> - 创建任务")
        print("  delete <task_id> - 删除任务")
        print("  status         - 显示状态")
        print("  quit           - 退出")
        print("="*60 + "\n")
    
    async def create_agent(self, name: str, port: int = 0) -> BrainNode:
        """创建大脑节点"""
        config = BrainConfig(name=name, port=port)
        agent = BrainNode(config)
        await agent.start()
        self.agents[name] = agent
        print(f"✅ 创建Agent: {name}")
        return agent
    
    async def create_muscle(self, name: str, port: int = 0) -> MuscleNode:
        """创建肌肉节点"""
        config = MuscleConfig(name=name, port=port)
        muscle = MuscleNode(config)
        await muscle.start()
        self.muscles[name] = muscle
        print(f"✅ 创建Muscle: {name}")
        return muscle
    
    def list_agents(self):
        """列出所有Agent"""
        print("\n📋 Agents:")
        for name, agent in self.agents.items():
            status = agent.get_status()
            print(f"  - {name}: {status['state']}")
    
    def list_muscles(self):
        """列出所有Muscle节点"""
        print("\n💪 Muscles:")
        for name, muscle in self.muscles.items():
            status = muscle.get_status()
            print(f"  - {name}: tools={status['tools']}")
    
    def list_tasks(self):
        """列出所有任务"""
        print("\n📝 Tasks:")
        for agent in self.agents.values():
            tasks = agent.crdt.get_all_tasks()
            for task_id in tasks:
                task = agent.crdt.tasks.get(task_id)
                if not task:
                    continue
                state = task.state
                title = task.metadata.title
                creator = task.metadata.creator
                is_deleted = task.is_deleted
                
                status_icon = "🗑️" if is_deleted else {
                    "pending": "⏳",
                    "locked": "🔒",
                    "in_progress": "🔄",
                    "done": "✅",
                    "deleted": "🗑️"
                }.get(state, "❓")
                
                print(f"  - [{task_id[:12]}] {status_icon} {title} (by {creator})")
    
    async def create_task(self, title: str, creator: str = None):
        """创建任务"""
        if not self.agents:
            print("❌ 没有可用的Agent")
            return
        
        agent_name = list(self.agents.keys())[0]
        agent = self.agents[agent_name]
        
        actual_creator = creator or agent_name
        task = await agent.create_task(title, creator=actual_creator)
        print(f"✅ 创建任务: {task.id} - {title}")
        
        self._tasks[task.id] = {
            "title": title,
            "creator": actual_creator,
            "agent": agent_name
        }
    
    async def delete_task(self, task_id: str):
        """删除任务"""
        if task_id not in self._tasks:
            print(f"❌ 任务不存在: {task_id}")
            return
        
        task_info = self._tasks[task_id]
        agent = self.agents.get(task_info["agent"])
        
        if not agent:
            print(f"❌ Agent不存在: {task_info['agent']}")
            return
        
        success, message = await agent.delete_task(task_id)
        if success:
            print(f"✅ {message}")
            del self._tasks[task_id]
        else:
            print(f"❌ {message}")
    
    def show_status(self):
        """显示状态"""
        print("\n" + "="*60)
        print("📊 系统状态")
        print("="*60)
        
        total_agents = len(self.agents)
        total_muscles = len(self.muscles)
        total_tasks = sum(len(a.crdt.get_all_tasks()) for a in self.agents.values())
        
        print(f"Agents: {total_agents}")
        print(f"Muscles: {total_muscles}")
        print(f"Tasks: {total_tasks}")
        
        for name, agent in self.agents.items():
            stats = agent.crdt.get_stats()
            print(f"\n{name}:")
            print(f"  Pending: {stats['pending']}")
            print(f"  Locked: {stats['locked']}")
            print(f"  In Progress: {stats['in_progress']}")
            print(f"  Done: {stats['done']}")
            print(f"  Deleted: {stats.get('deleted', 0)}")
        
        print("="*60 + "\n")
    
    async def run(self):
        """运行UI循环"""
        print("\n输入命令 (help 查看帮助):")
        
        while self.running:
            try:
                cmd = await asyncio.get_console_input()
                
                if not cmd:
                    continue
                
                cmd = cmd.strip().lower()
                
                if cmd == "help":
                    self.show_help()
                elif cmd == "list agents":
                    self.list_agents()
                elif cmd == "list muscles":
                    self.list_muscles()
                elif cmd == "list tasks":
                    self.list_tasks()
                elif cmd.startswith("create "):
                    title = cmd[7:].strip()
                    await self.create_task(title)
                elif cmd.startswith("delete "):
                    task_id = cmd.split()[1].strip()
                    await self.delete_task(task_id)
                elif cmd == "status":
                    self.show_status()
                elif cmd in ["quit", "exit", "q"]:
                    self.running = False
                    print("\n正在关闭所有节点...")
                    for agent in self.agents.values():
                        await agent.stop()
                    for muscle in self.muscles.values():
                        await muscle.stop()
                    print("👋 再见!")
                    break
                else:
                    print(f"❌ 未知命令: {cmd}")
                    print("输入 help 查看帮助")
            
            except Exception as e:
                print(f"❌ 错误: {e}")
    
    def show_help(self):
        """显示帮助"""
        print("\n" + "="*60)
        print("📖 娡拟终端UI帮助")
        print("="*60)
        print("""
命令:
  help              - 显示帮助
  list agents      - 列出所有Agent
  list muscles     - 列出所有Muscle节点
  list tasks       - 列出所有任务
  create <title> - 创建任务
  delete <task_id> - 删除任务
  status         - 显示状态
  quit           - 退出
        """)
        print("="*60 + "\n")


async def main():
    ui = TerminalUI()
    
    try:
        await ui.run()
    except KeyboardInterrupt:
        print("\n正在关闭...")
        ui.running = False
        for agent in ui.agents.values():
            await agent.stop()
        for muscle in ui.muscles.values():
            await muscle.stop()


if __name__ == "__main__":
    asyncio.run(main())
