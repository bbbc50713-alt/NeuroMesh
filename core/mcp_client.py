"""
MCP 客户端 - 启动 MCP Server 进程并通信

功能:
1. 启动 MCP Server 进程
2. 通过 stdio 与 MCP 通信
3. 调用工具并获取结果
"""

import asyncio
import json
import os
import sys
import subprocess
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import uuid


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]


class MCPClient:
    """MCP 客户端 - 与 MCP Server 通信"""
    
    def __init__(self, name: str, command: str, args: List[str] = None, env: Dict[str, str] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        
        self.process: Optional[subprocess.Popen] = None
        self.tools: List[MCPTool] = []
        self._initialized = False
        self._request_id = 0
    
    async def start(self) -> bool:
        """启动 MCP Server"""
        try:
            full_env = os.environ.copy()
            full_env.update(self.env)
            
            cmd = [self.command] + self.args
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
                bufsize=1
            )
            
            await asyncio.sleep(1)
            
            if self.process.poll() is not None:
                stderr = self.process.stderr.read()
                print(f"❌ MCP Server 启动失败: {stderr}")
                return False
            
            if not await self._initialize():
                return False
            
            await self._discover_tools()
            
            self._initialized = True
            print(f"✅ MCP Server [{self.name}] 启动成功，发现 {len(self.tools)} 个工具")
            return True
            
        except Exception as e:
            print(f"❌ MCP Server 启动异常: {e}")
            return False
    
    async def stop(self):
        """停止 MCP Server"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None
            self._initialized = False
    
    def _send_request(self, method: str, params: Dict = None) -> Dict:
        """发送 JSON-RPC 请求"""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            request_str = json.dumps(request) + "\n"
            self.process.stdin.write(request_str)
            self.process.stdin.flush()
            
            response_str = self.process.stdout.readline()
            if response_str:
                return json.loads(response_str)
        except Exception as e:
            print(f"❌ MCP 通信错误: {e}")
        
        return {"error": str(e) if 'e' in dir() else "Unknown error"}
    
    async def _initialize(self) -> bool:
        """初始化 MCP 连接"""
        response = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "agent-libp2p",
                "version": "1.0.0"
            }
        })
        
        if "error" in response:
            print(f"❌ MCP 初始化失败: {response['error']}")
            return False
        
        self._send_request("notifications/initialized", {})
        return True
    
    async def _discover_tools(self):
        """发现 MCP 工具"""
        response = self._send_request("tools/list", {})
        
        if "result" in response and "tools" in response["result"]:
            for tool_data in response["result"]["tools"]:
                tool = MCPTool(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {})
                )
                self.tools.append(tool)
    
    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """调用 MCP 工具"""
        if not self._initialized:
            return {"error": "MCP Server 未初始化"}
        
        response = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        
        if "error" in response:
            return {"error": response["error"]}
        
        result = response.get("result", {})
        
        if "content" in result:
            for content in result["content"]:
                if content.get("type") == "text":
                    return {"success": True, "result": content.get("text", "")}
        
        return {"success": True, "result": result}
    
    def get_tool_definitions(self) -> List[Dict]:
        """获取工具定义（用于 LLM function calling）"""
        definitions = []
        for tool in self.tools:
            definitions.append({
                "type": "function",
                "function": {
                    "name": f"mcp_{self.name}_{tool.name}",
                    "description": tool.description,
                    "parameters": tool.input_schema
                }
            })
        return definitions


class MCPClientManager:
    """MCP 客户端管理器"""
    
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
    
    async def start_client(self, name: str, command: str, args: List[str] = None, 
                           env: Dict[str, str] = None) -> bool:
        """启动 MCP 客户端"""
        if name in self.clients:
            return True
        
        client = MCPClient(name, command, args, env)
        success = await client.start()
        
        if success:
            self.clients[name] = client
            return True
        return False
    
    async def stop_client(self, name: str):
        """停止 MCP 客户端"""
        if name in self.clients:
            await self.clients[name].stop()
            del self.clients[name]
    
    async def stop_all(self):
        """停止所有客户端"""
        for name in list(self.clients.keys()):
            await self.stop_client(name)
    
    def get_client(self, name: str) -> Optional[MCPClient]:
        """获取客户端"""
        return self.clients.get(name)
    
    def get_all_tools(self) -> List[Dict]:
        """获取所有工具定义"""
        all_tools = []
        for client in self.clients.values():
            all_tools.extend(client.get_tool_definitions())
        return all_tools
    
    async def call_tool(self, full_tool_name: str, arguments: Dict) -> Dict:
        """调用工具（通过完整工具名）"""
        # 格式: mcp_{server_name}_{tool_name}
        parts = full_tool_name.split("_", 2)
        if len(parts) < 3:
            return {"error": f"无效的工具名: {full_tool_name}"}
        
        server_name = parts[1]
        tool_name = parts[2]
        
        client = self.get_client(server_name)
        if not client:
            return {"error": f"MCP Server 未启动: {server_name}"}
        
        return await client.call_tool(tool_name, arguments)
