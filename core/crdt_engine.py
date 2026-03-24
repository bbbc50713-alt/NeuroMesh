"""
CRDT核心引擎 - 基于Lamport Clock的真正无冲突数据类型

核心设计:
1. Lamport Clock: 解决时钟不同步问题
2. CRDT比较规则: [逻辑时钟, 节点ID] 确定最终状态
3. 租约机制: 任务抢占和失败恢复
"""

import time
import uuid
import json
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class LamportClock:
    """
    Lamport逻辑时钟 - 解决分布式系统中的事件排序问题
    
    规则:
    1. 本地事件: time += 1
    2. 发送消息: time += 1, 携带时间戳
    3. 接收消息: time = max(local_time, received_time) + 1
    """
    node_id: str
    time: int = 0
    
    def tick(self) -> int:
        self.time += 1
        return self.time
    
    def update(self, received_time: int) -> int:
        self.time = max(self.time, received_time) + 1
        return self.time
    
    def get_timestamp(self) -> Tuple[int, str]:
        return (self.time, self.node_id)


def crdt_compare(v1: Tuple[int, str], v2: Tuple[int, str]) -> int:
    """
    CRDT版本比较
    
    返回:
        1: v1更新
        -1: v2更新
        0: 相等(理论上不会发生，因为node_id唯一)
    
    比较规则:
    1. 逻辑时钟大的胜出
    2. 逻辑时钟相等时，节点ID字典序大的胜出
    """
    v1_time, v1_node = v1
    v2_time, v2_node = v2
    
    if v1_time > v2_time:
        return 1
    elif v1_time < v2_time:
        return -1
    else:
        return 1 if v1_node > v2_node else -1


@dataclass
class TodoItem:
    """
    Todo任务项 - CRDT数据结构
    
    核心字段:
    - version: (逻辑时钟, 节点ID) 用于CRDT比较
    - lock_until: 租约过期时间，用于任务抢占
    """
    id: str
    title: str
    status: str = "pending"
    assignee: Optional[str] = None
    lock_until: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    v_time: int = 0
    v_node: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TodoItem":
        return cls(**data)
    
    def get_version(self) -> Tuple[int, str]:
        return (self.v_time, self.v_node)


class CRDTStore:
    """
    CRDT存储引擎
    
    核心能力:
    1. 无冲突合并 - 基于Lamport Clock
    2. 任务抢占 - 基于租约机制
    3. 失败恢复 - 检测死节点并回收任务
    4. 心跳追踪 - 记录节点活跃状态
    """
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.clock = LamportClock(node_id)
        self.todos: Dict[str, TodoItem] = {}
        self.heartbeats: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        self._init_heartbeat()
    
    def _init_heartbeat(self):
        self.heartbeats[self.node_id] = time.time()
    
    def create_todo(self, title: str, metadata: Dict = None) -> TodoItem:
        """创建新任务"""
        with self._lock:
            todo_id = str(uuid.uuid4())
            t = self.clock.tick()
            
            todo = TodoItem(
                id=todo_id,
                title=title,
                status=TaskStatus.PENDING.value,
                v_time=t,
                v_node=self.node_id,
                metadata=metadata or {}
            )
            
            self.todos[todo_id] = todo
            return todo
    
    def _set_state(self, todo_id: str, **kwargs) -> bool:
        """内部方法：更新任务状态并递增版本"""
        with self._lock:
            if todo_id not in self.todos:
                return False
            
            todo = self.todos[todo_id]
            t = self.clock.tick()
            
            for key, value in kwargs.items():
                if hasattr(todo, key):
                    setattr(todo, key, value)
            
            todo.v_time = t
            todo.v_node = self.node_id
            todo.updated_at = time.time()
            
            return True
    
    def merge(self, remote_data: Dict) -> bool:
        """
        CRDT合并操作 - 核心方法
        
        合并规则:
        1. 本地不存在 -> 直接添加
        2. 本地存在 -> 比较版本，新版本覆盖旧版本
        3. 更新本地时钟以保持同步
        """
        with self._lock:
            changed = False
            
            remote_version = (remote_data.get("v_time", 0), remote_data.get("v_node", ""))
            todo_id = remote_data.get("id")
            
            if not todo_id:
                return False
            
            if todo_id not in self.todos:
                self.todos[todo_id] = TodoItem.from_dict(remote_data)
                self.clock.update(remote_version[0])
                changed = True
            else:
                local = self.todos[todo_id]
                local_version = local.get_version()
                
                cmp = crdt_compare(remote_version, local_version)
                
                if cmp > 0:
                    self.todos[todo_id] = TodoItem.from_dict(remote_data)
                    self.clock.update(remote_version[0])
                    changed = True
            
            return changed
    
    def merge_batch(self, remote_todos: Dict[str, Dict]) -> int:
        """批量合并"""
        changed_count = 0
        for todo_data in remote_todos.values():
            if self.merge(todo_data):
                changed_count += 1
        return changed_count
    
    def try_lock_task(self, todo_id: str, lease_seconds: int = 30) -> bool:
        """
        尝试抢占任务 - 租约机制
        
        抢占条件:
        1. 任务状态为pending
        2. 或者任务状态为in_progress但租约已过期(死节点恢复)
        """
        with self._lock:
            if todo_id not in self.todos:
                return False
            
            todo = self.todos[todo_id]
            now = int(time.time())
            
            can_lock = (
                todo.status == TaskStatus.PENDING.value or
                (todo.status == TaskStatus.IN_PROGRESS.value and now > todo.lock_until)
            )
            
            if can_lock:
                self._set_state(
                    todo_id,
                    status=TaskStatus.IN_PROGRESS.value,
                    assignee=self.node_id,
                    lock_until=now + lease_seconds
                )
                return True
            
            return False
    
    def complete_task(self, todo_id: str) -> bool:
        """完成任务"""
        with self._lock:
            if todo_id not in self.todos:
                return False
            
            todo = self.todos[todo_id]
            if todo.assignee != self.node_id:
                return False
            
            self._set_state(
                todo_id,
                status=TaskStatus.DONE.value,
                assignee=None,
                lock_until=0
            )
            return True
    
    def release_task(self, todo_id: str) -> bool:
        """释放任务（未完成时释放）"""
        with self._lock:
            if todo_id not in self.todos:
                return False
            
            todo = self.todos[todo_id]
            if todo.assignee != self.node_id:
                return False
            
            self._set_state(
                todo_id,
                status=TaskStatus.PENDING.value,
                assignee=None,
                lock_until=0
            )
            return True
    
    def update_heartbeat(self, agent_id: str):
        """更新节点心跳"""
        with self._lock:
            self.heartbeats[agent_id] = time.time()
    
    def is_node_alive(self, agent_id: str, timeout: float = 15.0) -> bool:
        """检查节点是否存活"""
        with self._lock:
            last_heartbeat = self.heartbeats.get(agent_id, 0)
            return (time.time() - last_heartbeat) < timeout
    
    def recover_dead_tasks(self, timeout: float = 15.0) -> list:
        """
        恢复死节点的任务
        
        返回: 被恢复的任务ID列表
        """
        recovered = []
        with self._lock:
            now = int(time.time())
            
            for todo_id, todo in list(self.todos.items()):
                if todo.status == TaskStatus.IN_PROGRESS.value:
                    if not self.is_node_alive(todo.assignee, timeout):
                        if now > todo.lock_until:
                            self._set_state(
                                todo_id,
                                status=TaskStatus.PENDING.value,
                                assignee=None,
                                lock_until=0
                            )
                            recovered.append(todo_id)
            
        return recovered
    
    def get_all_todos(self) -> Dict[str, Dict]:
        """获取所有任务（字典格式）"""
        with self._lock:
            return {tid: todo.to_dict() for tid, todo in self.todos.items()}
    
    def get_pending_todos(self) -> list:
        """获取待处理任务"""
        with self._lock:
            return [
                todo for todo in self.todos.values()
                if todo.status == TaskStatus.PENDING.value
            ]
    
    def get_my_tasks(self) -> list:
        """获取当前节点负责的任务"""
        with self._lock:
            return [
                todo for todo in self.todos.values()
                if todo.assignee == self.node_id
            ]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            stats = {
                "total": len(self.todos),
                "pending": 0,
                "in_progress": 0,
                "done": 0,
                "alive_nodes": len([a for a, t in self.heartbeats.items() 
                                   if time.time() - t < 15.0])
            }
            
            for todo in self.todos.values():
                if todo.status == TaskStatus.PENDING.value:
                    stats["pending"] += 1
                elif todo.status == TaskStatus.IN_PROGRESS.value:
                    stats["in_progress"] += 1
                elif todo.status == TaskStatus.DONE.value:
                    stats["done"] += 1
            
            return stats
