"""
MCP工具节点启动器

用于将本地MCP工具和Skills注册到P2P网络，让其他节点可以发现和调用。

使用方法:
    python run_mcp_node.py --name MyMCP --port 10000
    
    # 指定配置文件
    python run_mcp_node.py --config mcp_config.json
    
    # 连接到已有网络
    python run_mcp_node.py --name MyMCP --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/xxx
"""

import asyncio
import json
import sys
import os
import importlib.util
from typing import Dict, List, Any, Callable, Awaitable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.muscle_node import MuscleNode, MuscleConfig


def load_mcp_tools_from_file(file_path: str) -> List[Dict]:
    """
    从Python文件加载MCP工具定义
    
    文件格式示例:
    ```python
    # mcp_tools.py
    TOOLS = [
        {
            "name": "weather_query",
            "description": "查询天气信息",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                },
                "required": ["city"]
            },
            "handler": "query_weather"  # 函数名
        }
    ]
    
    async def query_weather(args):
        city = args.get("city")
        return {"city": city, "weather": "晴天", "temp": 25}
    ```
    """
    spec = importlib.util.spec_from_file_location("mcp_tools", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    tools = getattr(module, "TOOLS", [])
    
    loaded_tools = []
    for tool_def in tools:
        handler_name = tool_def.get("handler")
        if handler_name and hasattr(module, handler_name):
            tool_def["handler_func"] = getattr(module, handler_name)
            loaded_tools.append(tool_def)
    
    return loaded_tools


def load_skills_from_file(file_path: str) -> List[Dict]:
    """
    从配置文件加载Skills定义
    
    配置文件格式:
    ```json
    {
        "skills": [
            {
                "name": "data_analysis",
                "description": "数据分析技能",
                "capabilities": ["csv", "excel", "json"],
                "tools": ["pandas", "numpy"]
            }
        ]
    }
    ```
    """
    with open(file_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config.get("skills", [])


class MCPNodeLauncher:
    """
    MCP节点启动器
    
    功能:
    1. 加载本地MCP工具
    2. 加载Skills定义
    3. 注册到P2P网络
    4. 广播心跳让其他节点发现
    """
    
    def __init__(self, name: str, port: int = 0, bootstrap_peers: List[str] = None):
        self.name = name
        self.port = port
        self.bootstrap_peers = bootstrap_peers or []
        
        self.config = MuscleConfig(
            name=name,
            port=port,
            bootstrap_peers=bootstrap_peers
        )
        
        self.node = MuscleNode(self.config)
        self._tools: Dict[str, Callable] = {}
        self._skills: List[Dict] = []
    
    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        input_schema: Dict = None,
        tags: List[str] = None
    ):
        """
        注册单个MCP工具
        
        Args:
            name: 工具名称 (如 mcp/weather_query)
            description: 工具描述
            handler: 异步处理函数 async handler(args) -> result
            input_schema: 输入参数schema
            tags: 工具标签
        """
        self.node.register_tool(
            name=name,
            description=description,
            handler=handler,
            input_schema=input_schema
        )
        
        self._tools[name] = handler
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        print(f"✅ 注册工具: {name}{tag_str}")
    
    def register_skill(
        self,
        name: str,
        description: str,
        capabilities: List[str] = None,
        tools: List[str] = None
    ):
        """
        注册Skill（技能）
        
        Args:
            name: 技能名称
            description: 技能描述
            capabilities: 能力列表
            tools: 依赖工具列表
        """
        skill = {
            "name": name,
            "description": description,
            "capabilities": capabilities or [],
            "tools": tools or []
        }
        
        self._skills.append(skill)
        print(f"✅ 注册技能: {name} -> {capabilities}")
    
    def load_tools_from_file(self, file_path: str):
        """从文件批量加载工具"""
        tools = load_mcp_tools_from_file(file_path)
        
        for tool_def in tools:
            self.register_tool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                handler=tool_def["handler_func"],
                input_schema=tool_def.get("input_schema"),
                tags=tool_def.get("tags")
            )
        
        print(f"📦 从 {file_path} 加载了 {len(tools)} 个工具")
    
    def load_skills_from_file(self, file_path: str):
        """从文件批量加载技能"""
        skills = load_skills_from_file(file_path)
        
        for skill in skills:
            self.register_skill(
                name=skill["name"],
                description=skill.get("description", ""),
                capabilities=skill.get("capabilities"),
                tools=skill.get("tools")
            )
        
        print(f"📦 从 {file_path} 加载了 {len(skills)} 个技能")
    
    async def start(self):
        """启动节点"""
        await self.node.start()
        
        print(f"\n{'='*60}")
        print(f"🚀 MCP节点已启动!")
        print(f"{'='*60}")
        print(f"   节点名称: {self.name}")
        print(f"   监听端口: {self.port}")
        print(f"   已注册工具: {len(self._tools)}")
        print(f"   已注册技能: {len(self._skills)}")
        print(f"{'='*60}\n")
    
    async def stop(self):
        """停止节点"""
        await self.node.stop()
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "name": self.name,
            "tools": list(self._tools.keys()),
            "skills": self._skills,
            "node_status": self.node.get_status()
        }


async def interactive_mode(launcher: MCPNodeLauncher):
    """交互模式"""
    print("\n进入交互模式 (输入 help 查看命令)\n")
    
    while True:
        try:
            cmd = input("mcp-node> ").strip()
            
            if not cmd:
                continue
            
            parts = cmd.split()
            action = parts[0].lower()
            
            if action in ["exit", "quit", "q"]:
                print("退出...")
                break
            
            elif action == "help":
                print("""
可用命令:
  status          - 查看节点状态
  tools           - 列出所有工具
  skills          - 列出所有技能
  call <tool>     - 测试调用工具
  register        - 注册新工具
  exit            - 退出
""")
            
            elif action == "status":
                status = launcher.get_status()
                print(json.dumps(status, indent=2, ensure_ascii=False))
            
            elif action == "tools":
                print("\n已注册工具:")
                for name in launcher._tools.keys():
                    print(f"  - {name}")
            
            elif action == "skills":
                print("\n已注册技能:")
                for skill in launcher._skills:
                    print(f"  - {skill['name']}: {skill.get('capabilities', [])}")
            
            elif action == "call":
                if len(parts) < 2:
                    print("用法: call <tool_name> [args_json]")
                    continue
                
                tool_name = parts[1]
                args = {}
                if len(parts) > 2:
                    try:
                        args = json.loads(" ".join(parts[2:]))
                    except:
                        args = {"arg": " ".join(parts[2:])}
                
                if tool_name in launcher._tools:
                    handler = launcher._tools[tool_name]
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(args)
                    else:
                        result = handler(args)
                    print(f"结果: {result}")
                else:
                    print(f"工具不存在: {tool_name}")
            
            elif action == "register":
                print("请使用代码注册工具，或在启动时指定配置文件")
            
            else:
                print(f"未知命令: {action}")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"错误: {e}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="启动MCP工具节点")
    parser.add_argument("--name", default="MCP-Node", help="节点名称")
    parser.add_argument("--port", type=int, default=0, help="监听端口")
    parser.add_argument("--bootstrap", nargs="*", default=[], help="Bootstrap节点地址")
    parser.add_argument("--tools-file", help="工具定义文件路径")
    parser.add_argument("--skills-file", help="技能定义文件路径")
    parser.add_argument("--interactive", action="store_true", help="进入交互模式")
    
    args = parser.parse_args()
    
    launcher = MCPNodeLauncher(
        name=args.name,
        port=args.port,
        bootstrap_peers=args.bootstrap
    )
    
    if args.tools_file:
        launcher.load_tools_from_file(args.tools_file)
    
    if args.skills_file:
        launcher.load_skills_from_file(args.skills_file)
    
    if not args.tools_file:
        print("注册默认示例工具...")
        
        async def example_query(args):
            return {"result": f"处理了: {args}"}
        
        launcher.register_tool(
            name="mcp/example_query",
            description="示例查询工具",
            handler=example_query,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询内容"}
                }
            },
            tags=["example", "query"]
        )
        
        launcher.register_skill(
            name="data_processing",
            description="数据处理技能",
            capabilities=["csv", "json", "excel"],
            tools=["pandas", "numpy"]
        )
    
    await launcher.start()
    
    if args.interactive:
        await interactive_mode(launcher)
    else:
        print("节点运行中，按 Ctrl+C 退出...")
        try:
            while True:
                await asyncio.sleep(10)
                print(f"💓 心跳: {launcher.name} 在线, 工具: {len(launcher._tools)}")
        except KeyboardInterrupt:
            pass
    
    await launcher.stop()


if __name__ == "__main__":
    asyncio.run(main())
