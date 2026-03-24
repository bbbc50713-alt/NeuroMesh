"""
MCP 管理模块 - 管理 MCP Server 配置

功能:
1. 添加 MCP 配置
2. 删除 MCP 配置
3. 列出 MCP 配置
4. 发现可用 MCP
5. 挂载到节点
"""

import json
import os
import shutil
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
from pathlib import Path


MCP_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp.json")
MCP_MOUNT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_mounts.json")


@dataclass
class MCPServerConfig:
    """MCP Server 配置"""
    command: str
    args: List[str] = None
    env: Dict[str, str] = None
    disabled: bool = False
    autoApprove: List[str] = None
    mounted_to: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if self.args is None:
            self.args = []
        if self.env is None:
            self.env = {}
        if self.autoApprove is None:
            self.autoApprove = []
        if self.mounted_to is None:
            self.mounted_to = []
    
    def to_dict(self) -> Dict:
        result = {"command": self.command}
        if self.args:
            result["args"] = self.args
        if self.env:
            result["env"] = self.env
        if self.disabled:
            result["disabled"] = self.disabled
        if self.autoApprove:
            result["autoApprove"] = self.autoApprove
        if self.mounted_to:
            result["mounted_to"] = self.mounted_to
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPServerConfig":
        return cls(
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            disabled=data.get("disabled", False),
            autoApprove=data.get("autoApprove", []),
            mounted_to=data.get("mounted_to", [])
        )


class MCPManager:
    """MCP 配置管理器"""
    
    def __init__(self, config_path: str = MCP_CONFIG_PATH, mount_path: str = MCP_MOUNT_PATH):
        self.config_path = config_path
        self.mount_path = mount_path
        self._ensure_config_exists()
    
    def _ensure_config_exists(self):
        """确保配置文件存在"""
        if not os.path.exists(self.config_path):
            self._save_config({"mcpServers": {}})
        if not os.path.exists(self.mount_path):
            self._save_mounts({"mounts": {}})
    
    def _load_config(self) -> Dict:
        """加载配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"mcpServers": {}}
    
    def _save_config(self, config: Dict):
        """保存配置"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def _load_mounts(self) -> Dict:
        """加载挂载配置"""
        try:
            with open(self.mount_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"mounts": {}}
    
    def _save_mounts(self, mounts: Dict):
        """保存挂载配置"""
        os.makedirs(os.path.dirname(self.mount_path), exist_ok=True)
        with open(self.mount_path, "w", encoding="utf-8") as f:
            json.dump(mounts, f, indent=2, ensure_ascii=False)
    
    def list_servers(self) -> Dict[str, MCPServerConfig]:
        """列出所有 MCP Server"""
        config = self._load_config()
        servers = {}
        for name, server_data in config.get("mcpServers", {}).items():
            servers[name] = MCPServerConfig.from_dict(server_data)
        return servers
    
    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """获取单个 MCP Server"""
        servers = self.list_servers()
        return servers.get(name)
    
    def add_server(self, name: str, config: MCPServerConfig) -> bool:
        """添加 MCP Server"""
        full_config = self._load_config()
        if "mcpServers" not in full_config:
            full_config["mcpServers"] = {}
        
        if name in full_config["mcpServers"]:
            return False
        
        full_config["mcpServers"][name] = config.to_dict()
        self._save_config(full_config)
        return True
    
    def update_server(self, name: str, config: MCPServerConfig) -> bool:
        """更新 MCP Server"""
        full_config = self._load_config()
        if name not in full_config.get("mcpServers", {}):
            return False
        
        full_config["mcpServers"][name] = config.to_dict()
        self._save_config(full_config)
        return True
    
    def delete_server(self, name: str) -> bool:
        """删除 MCP Server"""
        full_config = self._load_config()
        if name not in full_config.get("mcpServers", {}):
            return False
        
        del full_config["mcpServers"][name]
        self._save_config(full_config)
        
        # 同时清除挂载关系
        self._remove_all_mounts_for_mcp(name)
        return True
    
    def enable_server(self, name: str) -> bool:
        """启用 MCP Server"""
        server = self.get_server(name)
        if not server:
            return False
        server.disabled = False
        return self.update_server(name, server)
    
    def disable_server(self, name: str) -> bool:
        """禁用 MCP Server"""
        server = self.get_server(name)
        if not server:
            return False
        server.disabled = True
        return self.update_server(name, server)
    
    def discover_npx_mcp(self) -> List[Dict]:
        """发现可通过 npx 安装的 MCP"""
        common_mcp_servers = [
            {
                "name": "filesystem",
                "description": "文件系统操作",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
            },
            {
                "name": "github",
                "description": "GitHub API 集成",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"]
            },
            {
                "name": "postgres",
                "description": "PostgreSQL 数据库",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres"]
            },
            {
                "name": "sqlite",
                "description": "SQLite 数据库",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-sqlite"]
            },
            {
                "name": "brave-search",
                "description": "Brave 搜索",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"]
            },
            {
                "name": "puppeteer",
                "description": "浏览器自动化",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
            },
            {
                "name": "slack",
                "description": "Slack 集成",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-slack"]
            },
            {
                "name": "memory",
                "description": "持久化内存存储",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"]
            }
        ]
        return common_mcp_servers
    
    def import_from_trae_config(self, trae_config_path: str) -> int:
        """从 Trae 配置文件导入 MCP"""
        try:
            with open(trae_config_path, "r", encoding="utf-8") as f:
                trae_config = json.load(f)
            
            imported = 0
            for name, server_data in trae_config.get("mcpServers", {}).items():
                config = MCPServerConfig.from_dict(server_data)
                if self.add_server(name, config):
                    imported += 1
            
            return imported
        except Exception as e:
            print(f"导入失败: {e}")
            return 0
    
    def export_to_trae_format(self) -> Dict:
        """导出为 Trae 格式"""
        return self._load_config()
    
    def get_mountable_servers(self) -> Dict[str, MCPServerConfig]:
        """获取可挂载的 MCP Server（未禁用的）"""
        servers = self.list_servers()
        return {name: config for name, config in servers.items() if not config.disabled}
    
    # ==================== 挂载功能 ====================
    
    def mount_to_node(self, mcp_name: str, node_name: str) -> bool:
        """将 MCP 挂载到节点"""
        server = self.get_server(mcp_name)
        if not server or server.disabled:
            return False
        
        if node_name not in server.mounted_to:
            server.mounted_to.append(node_name)
            return self.update_server(mcp_name, server)
        return True
    
    def unmount_from_node(self, mcp_name: str, node_name: str) -> bool:
        """从节点卸载 MCP"""
        server = self.get_server(mcp_name)
        if not server:
            return False
        
        if node_name in server.mounted_to:
            server.mounted_to.remove(node_name)
            return self.update_server(mcp_name, server)
        return True
    
    def get_mounted_mcps(self, node_name: str) -> List[MCPServerConfig]:
        """获取节点挂载的 MCP"""
        servers = self.list_servers()
        return [s for s in servers.values() if node_name in s.mounted_to and not s.disabled]
    
    def get_mounted_mcp_names(self, node_name: str) -> List[str]:
        """获取节点挂载的 MCP 名称列表"""
        servers = self.list_servers()
        return [name for name, s in servers.items() if node_name in s.mounted_to and not s.disabled]
    
    def _remove_all_mounts_for_mcp(self, mcp_name: str):
        """移除 MCP 的所有挂载关系"""
        server = self.get_server(mcp_name)
        if server:
            server.mounted_to = []
            self.update_server(mcp_name, server)
    
    def unmount_all_from_node(self, node_name: str) -> int:
        """从节点卸载所有 MCP"""
        servers = self.list_servers()
        count = 0
        for name, server in servers.items():
            if node_name in server.mounted_to:
                server.mounted_to.remove(node_name)
                self.update_server(name, server)
                count += 1
        return count
    
    def get_mount_summary(self) -> Dict[str, List[str]]:
        """获取挂载摘要：节点 -> MCP列表"""
        servers = self.list_servers()
        summary = {}
        for name, server in servers.items():
            if not server.disabled and server.mounted_to:
                for node in server.mounted_to:
                    if node not in summary:
                        summary[node] = []
                    summary[node].append(name)
        return summary


def create_mcp_config_from_template(name: str, command: str = "npx", 
                                     package: str = None, args: List[str] = None,
                                     env: Dict[str, str] = None) -> MCPServerConfig:
    """从模板创建 MCP 配置"""
    if args is None and package:
        args = ["-y", package]
    
    return MCPServerConfig(
        command=command,
        args=args or [],
        env=env or {}
    )
