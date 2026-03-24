"""
Agent P2P 多智能体协作框架

核心模块:
- core: CRDT引擎 + MCP协议
- network: P2P网络层
- agent: Agent节点
- server: 中心兜底服务器
"""

__version__ = "1.0.0"

from core import LamportClock, CRDTStore, TodoItem, MCPRegistry, MCPTool
from network import P2PNetwork, P2PConfig
from agent import Agent, AgentConfig, AgentState

__all__ = [
    "LamportClock",
    "CRDTStore",
    "TodoItem",
    "MCPRegistry",
    "MCPTool",
    "P2PNetwork",
    "P2PConfig",
    "Agent",
    "AgentConfig",
    "AgentState",
]
