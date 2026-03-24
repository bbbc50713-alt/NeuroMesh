"""
中心兜底服务器

职责:
1. Bootstrap节点 - 帮助新节点发现网络
2. 数据持久化 - SQLite存储所有todo
3. CRDT合并中心 - 作为权威节点参与合并
4. 状态查询API - 提供全局状态视图
"""

import json
import time
import sqlite3
from typing import Dict, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.crdt_engine import CRDTStore, TodoItem


class TodoSyncRequest(BaseModel):
    id: str
    title: str
    status: str
    assignee: Optional[str] = None
    lock_until: int = 0
    created_at: float = 0
    updated_at: float = 0
    v_time: int = 0
    v_node: str = ""
    metadata: Dict = {}


class CentralServer:
    """
    中心兜底服务器
    
    核心功能:
    1. CRDT状态聚合
    2. 持久化存储
    3. Bootstrap服务
    """
    
    def __init__(self, db_path: str = "agent_todos.db"):
        self.db_path = db_path
        self.crdt_store = CRDTStore("Server-Backup")
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assignee TEXT,
                    lock_until INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL,
                    v_time INTEGER DEFAULT 0,
                    v_node TEXT,
                    metadata TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    last_seen REAL,
                    tools TEXT
                )
            """)
            
            conn.commit()
    
    @contextmanager
    def _get_db(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def sync_todo(self, todo_data: Dict) -> bool:
        """同步todo - 使用CRDT合并"""
        if self.crdt_store.merge(todo_data):
            self._persist_todo(todo_data)
            return True
        return False
    
    def _persist_todo(self, todo_data: Dict):
        """持久化todo"""
        with self._get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO todos 
                (id, title, status, assignee, lock_until, created_at, updated_at, v_time, v_node, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                todo_data.get("id"),
                todo_data.get("title"),
                todo_data.get("status"),
                todo_data.get("assignee"),
                todo_data.get("lock_until", 0),
                todo_data.get("created_at", time.time()),
                todo_data.get("updated_at", time.time()),
                todo_data.get("v_time", 0),
                todo_data.get("v_node", ""),
                json.dumps(todo_data.get("metadata", {}))
            ))
            conn.commit()
    
    def get_all_todos(self) -> Dict:
        """获取所有todo"""
        with self._get_db() as conn:
            rows = conn.execute("SELECT * FROM todos").fetchall()
            return {
                row["id"]: {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "assignee": row["assignee"],
                    "lock_until": row["lock_until"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "v_time": row["v_time"],
                    "v_node": row["v_node"],
                    "metadata": json.loads(row["metadata"] or "{}")
                }
                for row in rows
            }
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        todos = self.get_all_todos()
        stats = {
            "total": len(todos),
            "pending": 0,
            "in_progress": 0,
            "done": 0
        }
        for todo in todos.values():
            status = todo.get("status", "pending")
            if status in stats:
                stats[status] += 1
        return stats
    
    def register_node(self, node_id: str, tools: list = None):
        """注册节点"""
        with self._get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO nodes (node_id, last_seen, tools)
                VALUES (?, ?, ?)
            """, (node_id, time.time(), json.dumps(tools or [])))
            conn.commit()
    
    def get_active_nodes(self, timeout: float = 30.0) -> list:
        """获取活跃节点"""
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE last_seen > ?",
                (time.time() - timeout,)
            ).fetchall()
            return [
                {
                    "node_id": row["node_id"],
                    "last_seen": row["last_seen"],
                    "tools": json.loads(row["tools"] or "[]")
                }
                for row in rows
            ]


def create_app(db_path: str = "agent_todos.db") -> FastAPI:
    """创建FastAPI应用"""
    server = CentralServer(db_path)
    
    app = FastAPI(
        title="Agent P2P Central Server",
        description="中心兜底服务器 - Bootstrap + 持久化 + CRDT合并",
        version="1.0.0"
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/")
    async def root():
        return {"status": "ok", "service": "Agent P2P Central Server"}
    
    @app.get("/todos")
    async def get_todos():
        return server.get_all_todos()
    
    @app.get("/todos/{todo_id}")
    async def get_todo(todo_id: str):
        todos = server.get_all_todos()
        if todo_id not in todos:
            raise HTTPException(status_code=404, detail="Todo not found")
        return todos[todo_id]
    
    @app.post("/sync")
    async def sync_todo(todo: TodoSyncRequest):
        todo_data = todo.model_dump()
        changed = server.sync_todo(todo_data)
        return {"status": "merged" if changed else "no_change", "todo_id": todo.id}
    
    @app.post("/sync/batch")
    async def sync_batch(todos: Dict[str, Dict]):
        changed_count = 0
        for todo_data in todos.values():
            if server.sync_todo(todo_data):
                changed_count += 1
        return {"status": "ok", "merged_count": changed_count}
    
    @app.get("/stats")
    async def get_stats():
        return server.get_stats()
    
    @app.post("/nodes/{node_id}/register")
    async def register_node(node_id: str, tools: list = None):
        server.register_node(node_id, tools)
        return {"status": "ok"}
    
    @app.get("/nodes")
    async def get_nodes():
        return server.get_active_nodes()
    
    @app.get("/bootstrap")
    async def get_bootstrap():
        return {
            "todos": server.get_all_todos(),
            "nodes": server.get_active_nodes(),
            "stats": server.get_stats()
        }
    
    return app


def run_server(host: str = "0.0.0.0", port: int = 8000, db_path: str = "agent_todos.db"):
    """运行服务器"""
    app = create_app(db_path)
    print(f"Starting Central Server on {host}:{port}")
    print(f"Database: {db_path}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent P2P Central Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--db", default="agent_todos.db", help="Database path")
    
    args = parser.parse_args()
    run_server(args.host, args.port, args.db)
