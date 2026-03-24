"""
V2.0 增强版 CRDT 引擎

新增特性:
1. 租约机制 - 防止任务黑洞
2. 私有子网支持 - 公网挂牌+私网施工
3. 聊天消息支持 - 状态流+消息流双轨
"""

import time
import uuid
import json
from typing import Dict, Optional, Any, Tuple, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading


class TaskState(Enum):
    PENDING = "pending"
    LOCKED = "locked"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DELETED = "deleted"  # 墓碑状态


@dataclass
class LamportClock:
    node_id: str
    time: int = 0
    
    def tick(self) -> int:
        self.time += 1
        return self.time
    
    def update(self, received_time: int) -> int:
        self.time = max(self.time, received_time) + 1
        return self.time
    
    def get_version(self) -> Tuple[int, str]:
        return (self.time, self.node_id)


def crdt_compare(v1: Tuple[int, str], v2: Tuple[int, str]) -> int:
    v1_time, v1_node = v1
    v2_time, v2_node = v2
    
    if v1_time > v2_time:
        return 1
    elif v1_time < v2_time:
        return -1
    else:
        return 1 if v1_node > v2_node else -1


@dataclass
class TaskMetadata:
    title: str
    creator: str = "system"
    priority: int = 0
    tags: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Task:
    id: str
    metadata: TaskMetadata
    state: str = TaskState.PENDING.value
    assignee: Optional[str] = None
    subnet_topic: Optional[str] = None
    lease_expiry: int = 0
    v_time: int = 0
    v_node: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_deleted: bool = False  # 墓碑标记
    deleted_at: Optional[float] = None  # 删除时间
    deleted_by: Optional[str] = None  # 删除者
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data["metadata"] = asdict(self.metadata)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        metadata_data = data.pop("metadata", {})
        metadata = TaskMetadata(**metadata_data)
        return cls(metadata=metadata, **data)
    
    def is_tombstone(self) -> bool:
        """检查是否为墓碑"""
        return self.is_deleted or self.state == TaskState.DELETED.value


@dataclass
class ChatMessage:
    id: str
    sender: str
    content: str
    ref_task: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    is_private: bool = False
    
    def to_dict(self) -> Dict:
        return asdict(self)


class EnhancedCRDTStore:
    """
    V2.0 增强版 CRDT 存储
    
    核心能力:
    1. 任务管理 - 创建、锁定、完成
    2. 租约机制 - 超时自动回收
    3. 私有子网 - 动态创建和销毁
    4. 消息存储 - 聊天记录
    """
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.clock = LamportClock(node_id)
        self.tasks: Dict[str, Task] = {}
        self.messages: List[ChatMessage] = []
        self.muscle_registry: Dict[str, Dict] = {}
        self.heartbeats: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        self._init_heartbeat()
    
    def _init_heartbeat(self):
        self.heartbeats[self.node_id] = time.time()
    
    def create_task(
        self,
        title: str,
        creator: str = "system",
        priority: int = 0,
        tags: List[str] = None,
        description: str = ""
    ) -> Task:
        with self._lock:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            t = self.clock.tick()
            
            task = Task(
                id=task_id,
                metadata=TaskMetadata(
                    title=title,
                    creator=creator,
                    priority=priority,
                    tags=tags or [],
                    description=description
                ),
                v_time=t,
                v_node=self.node_id
            )
            
            self.tasks[task_id] = task
            return task
    
    def attempt_lock(self, task_id: str, lease_duration: int = 300) -> Optional[str]:
        """
        尝试抢占任务
        
        返回: 成功返回subnet_topic，失败返回None
        
        抢占条件:
        1. 任务状态为pending
        2. 或任务状态为locked但租约已过期(黑洞恢复)
        """
        with self._lock:
            if task_id not in self.tasks:
                return None
            
            task = self.tasks[task_id]
            now = int(time.time())
            
            can_lock = (
                task.state == TaskState.PENDING.value or
                (task.state == TaskState.LOCKED.value and now > task.lease_expiry) or
                (task.state == TaskState.IN_PROGRESS.value and now > task.lease_expiry)
            )
            
            if can_lock:
                subnet_topic = f"subnet_{task_id}_{uuid.uuid4().hex[:4]}"
                
                task.state = TaskState.LOCKED.value
                task.assignee = self.node_id
                task.subnet_topic = subnet_topic
                task.lease_expiry = now + lease_duration
                task.v_time = self.clock.tick()
                task.v_node = self.node_id
                task.updated_at = time.time()
                
                return subnet_topic
            
            return None
    
    def confirm_progress(self, task_id: str, lease_extension: int = 60) -> bool:
        """确认任务进行中，延长租约"""
        with self._lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            if task.assignee != self.node_id:
                return False
            
            task.state = TaskState.IN_PROGRESS.value
            task.lease_expiry = int(time.time()) + lease_extension
            task.v_time = self.clock.tick()
            task.v_node = self.node_id
            task.updated_at = time.time()
            
            return True
    
    def mark_done(self, task_id: str) -> bool:
        """标记任务完成"""
        with self._lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            if task.assignee != self.node_id:
                return False
            
            task.state = TaskState.DONE.value
            task.subnet_topic = None
            task.v_time = self.clock.tick()
            task.v_node = self.node_id
            task.updated_at = time.time()
            
            return True
    
    def delete_task(self, task_id: str) -> Tuple[bool, str]:
        """
        删除任务 - 只有创建者可以删除已完成的任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            (success, message): 成功状态和消息
            
        规则:
        1. 只有创建者可以删除任务
        2. 只能删除已完成的任务（state == done）
        3. 删除后会广播到全网
        """
        with self._lock:
            if task_id not in self.tasks:
                return False, f"任务不存在: {task_id}"
            
            task = self.tasks[task_id]
            creator = task.metadata.creator
            
            if creator != self.node_id:
                return False, f"无权删除: 只有创建者 '{creator}' 可以删除此任务"
            
            if task.state != TaskState.DONE.value:
                return False, f"只能删除已完成的任务，当前状态: {task.state}"
            
            del self.tasks[task_id]
            self.clock.tick()
            
            return True, f"任务已删除: {task_id}"
    
    def can_delete_task(self, task_id: str) -> Tuple[bool, str]:
        """
        检查是否可以删除任务（不实际删除）
        
        Returns:
            (can_delete, reason): 是否可删除及原因
        """
        with self._lock:
            if task_id not in self.tasks:
                return False, "任务不存在"
            
            task = self.tasks[task_id]
            creator = task.metadata.creator
            
            if creator != self.node_id:
                return False, f"只有创建者 '{creator}' 可以删除"
            
            if task.state != TaskState.DONE.value:
                return False, f"只能删除已完成的任务，当前状态: {task.state}"
            
            return True, "可以删除"
    
    def release_task(self, task_id: str) -> bool:
        """释放任务（未完成时）"""
        with self._lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            if task.assignee != self.node_id:
                return False
            
            task.state = TaskState.PENDING.value
            task.assignee = None
            task.subnet_topic = None
            task.lease_expiry = 0
            task.v_time = self.clock.tick()
            task.v_node = self.node_id
            task.updated_at = time.time()
            
            return True
    
    def merge_task(self, task_data: Dict) -> bool:
        """合并远程任务数据"""
        with self._lock:
            task_id = task_data.get("id")
            if not task_id:
                return False
            
            remote_version = (task_data.get("v_time", 0), task_data.get("v_node", ""))
            
            if task_id not in self.tasks:
                self.tasks[task_id] = Task.from_dict(task_data)
                self.clock.update(remote_version[0])
                return True
            
            local = self.tasks[task_id]
            local_version = (local.v_time, local.v_node)
            
            if crdt_compare(remote_version, local_version) > 0:
                self.tasks[task_id] = Task.from_dict(task_data)
                self.clock.update(remote_version[0])
                return True
            
            return False
    
    def merge_batch(self, tasks_data: Dict[str, Dict]) -> int:
        """批量合并"""
        count = 0
        for task_data in tasks_data.values():
            if self.merge_task(task_data):
                count += 1
        return count
    
    def recover_expired_tasks(self, timeout: float = 15.0) -> List[str]:
        """
        恢复过期任务
        
        返回: 被恢复的任务ID列表
        """
        recovered = []
        with self._lock:
            now = int(time.time())
            
            for task_id, task in list(self.tasks.items()):
                if task.state in [TaskState.LOCKED.value, TaskState.IN_PROGRESS.value]:
                    if now > task.lease_expiry:
                        if not self.is_node_alive(task.assignee, timeout):
                            task.state = TaskState.PENDING.value
                            task.assignee = None
                            task.subnet_topic = None
                            task.lease_expiry = 0
                            task.v_time = self.clock.tick()
                            task.v_node = self.node_id
                            task.updated_at = time.time()
                            recovered.append(task_id)
        
        return recovered
    
    def add_message(self, message: ChatMessage):
        """添加聊天消息"""
        with self._lock:
            self.messages.append(message)
            if len(self.messages) > 1000:
                self.messages = self.messages[-500:]
    
    def get_messages(self, ref_task: str = None, limit: int = 50) -> List[Dict]:
        """获取消息"""
        with self._lock:
            if ref_task:
                msgs = [m for m in self.messages if m.ref_task == ref_task]
            else:
                msgs = self.messages
            return [m.to_dict() for m in msgs[-limit:]]
    
    def register_muscle(self, node_id: str, capabilities: List[str]):
        """注册肌肉节点"""
        with self._lock:
            self.muscle_registry[node_id] = {
                "last_seen": time.time(),
                "capabilities": capabilities
            }
    
    def find_muscle(self, capability: str) -> Optional[str]:
        """查找具有特定能力的肌肉节点"""
        with self._lock:
            for node_id, info in self.muscle_registry.items():
                if capability in info.get("capabilities", []):
                    if time.time() - info["last_seen"] < 60:
                        return node_id
            return None
    
    def update_heartbeat(self, node_id: str):
        """更新心跳"""
        with self._lock:
            self.heartbeats[node_id] = time.time()
    
    def is_node_alive(self, node_id: str, timeout: float = 15.0) -> bool:
        """检查节点是否存活"""
        with self._lock:
            last = self.heartbeats.get(node_id, 0)
            return (time.time() - last) < timeout
    
    def get_all_tasks(self) -> Dict[str, Dict]:
        """获取所有任务"""
        with self._lock:
            return {tid: task.to_dict() for tid, task in self.tasks.items()}
    
    def get_pending_tasks(self) -> List[Task]:
        """获取待处理任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.state == TaskState.PENDING.value]
    
    def get_my_tasks(self) -> List[Task]:
        """获取我的任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.assignee == self.node_id]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            stats = {
                "total": len(self.tasks),
                "pending": 0,
                "locked": 0,
                "in_progress": 0,
                "done": 0,
                "muscles_available": len([
                    m for m, info in self.muscle_registry.items()
                    if time.time() - info["last_seen"] < 60
                ]),
                "alive_nodes": len([
                    n for n, t in self.heartbeats.items()
                    if time.time() - t < 15.0
                ])
            }
            
            for task in self.tasks.values():
                if task.state == TaskState.PENDING.value:
                    stats["pending"] += 1
                elif task.state == TaskState.LOCKED.value:
                    stats["locked"] += 1
                elif task.state == TaskState.IN_PROGRESS.value:
                    stats["in_progress"] += 1
                elif task.state == TaskState.DONE.value:
                    stats["done"] += 1
            
            return stats
