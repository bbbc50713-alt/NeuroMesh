# 🚀 MCP工具节点使用指南

## 快速开始

### 1. 基本启动

```bash
# 最简单的方式 - 启动一个MCP节点
python run_mcp_node.py --name MyMCP --interactive
```

### 2. 加载自定义工具和技能

```bash
# 加载工具定义文件
python run_mcp_node.py \
    --name MyMCP \
    --tools-file examples/mcp_tools_example.py \
    --skills-file examples/skills_config.json \
    --interactive
```

### 3. 连接到已有网络

```bash
# 连接到Bootstrap节点
python run_mcp_node.py \
    --name MyMCP \
    --port 10001 \
    --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/Brain-Main
```

---

## 📋 完整示例：启动一个天气查询节点

### 步骤1: 创建工具定义文件

创建 `my_weather_tools.py`:

```python
TOOLS = [
    {
        "name": "mcp/weather_query",
        "description": "查询指定城市的天气信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
        },
        "handler": "query_weather",
        "tags": ["weather", "query"]
    }
]

async def query_weather(args):
    """实际的天气查询逻辑"""
    city = args.get("city")
    
    # 这里可以调用真实的天气API
    # 例如: response = await httpx.get(f"https://api.weather.com/{city}")
    
    return {
        "city": city,
        "weather": "晴天",
        "temperature": 25,
        "humidity": 60
    }
```

### 步骤2: 启动节点

```bash
python run_mcp_node.py \
    --name Weather-Service \
    --tools-file my_weather_tools.py \
    --port 10010
```

### 步骤3: 节点自动上链

启动后，节点会自动：
1. ✅ 注册所有工具到本地
2. ✅ 广播心跳到P2P网络
3. ✅ 被其他节点发现

输出示例：
```
✅ 注册工具: mcp/weather_query
📦 从 my_weather_tools.py 加载了 1 个工具

💪 肌肉节点已上线!
   Node ID: Weather-Service
   监听地址: /ip4/127.0.0.1/tcp/10010/p2p/Weather-Service
   可用工具: ['mcp/weather_query']
   等待大脑节点调用...

💓 心跳: Weather-Service 在线, 工具: 1
```

---

## 🌐 多节点协作示例

### 终端1: 启动大脑节点

```bash
python -m agent.brain_node \
    --name Brain-Main \
    --port 10000
```

### 终端2: 启动天气服务（肌肉节点）

```bash
python run_mcp_node.py \
    --name Weather-Service \
    --tools-file examples/mcp_tools_example.py \
    --port 10001 \
    --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/Brain-Main
```

### 终端3: 启动数据库服务（肌肉节点）

```bash
python run_mcp_node.py \
    --name Database-Service \
    --tools-file examples/mcp_tools_example.py \
    --port 10002 \
    --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/Brain-Main
```

大脑节点会自动发现这些肌肉节点：
```
💪 发现肌肉节点: Weather-Service -> ['mcp/weather_query']
💪 发现肌肉节点: Database-Service -> ['mcp/database_query']
```

---

## 📡 如何被发现

### 自动发现机制

1. **心跳广播**（每15秒）
   ```python
   # 肌肉节点自动广播
   {
       "type": "muscle_announce",
       "node_id": "Weather-Service",
       "capabilities": ["mcp/weather_query"],
       "timestamp": 1705312345
   }
   ```

2. **大脑节点接收**
   ```python
   # 大脑节点自动注册
   muscle_registry["Weather-Service"] = {
       "last_seen": time.time(),
       "capabilities": ["mcp/weather_query"]
   }
   ```

3. **调用时发现**
   ```python
   # 大脑节点调用肌肉节点
   result = await brain.call_muscle("mcp/weather_query", {"city": "北京"})
   ```

---

## 🔧 高级配置

### 创建完整的MCP服务节点

```python
import asyncio
from run_mcp_node import MCPNodeLauncher

async def main():
    # 创建启动器
    launcher = MCPNodeLauncher(
        name="My-Service",
        port=10010,
        bootstrap_peers=["/ip4/127.0.0.1/tcp/10000/p2p/Brain-Main"]
    )
    
    # 注册工具
    async def my_tool(args):
        return {"result": "processed"}
    
    launcher.register_tool(
        name="mcp/my_tool",
        description="我的自定义工具",
        handler=my_tool,
        input_schema={
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            }
        },
        tags=["custom", "example"]
    )
    
    # 注册技能
    launcher.register_skill(
        name="data_analysis",
        description="数据分析技能",
        capabilities=["csv", "json", "excel"],
        tools=["pandas", "numpy"]
    )
    
    # 启动
    await launcher.start()
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        pass
    
    await launcher.stop()

asyncio.run(main())
```

---

## 📊 状态查询

### 交互模式命令

```bash
mcp-node> status
{
  "name": "My-Service",
  "tools": ["mcp/my_tool"],
  "skills": [{"name": "data_analysis", ...}],
  "node_status": {...}
}

mcp-node> tools
已注册工具:
  - mcp/my_tool

mcp-node> skills
已注册技能:
  - data_analysis: ['csv', 'json', 'excel']

mcp-node> call mcp/my_tool {"input": "test"}
结果: {"result": "processed"}
```

---

## 🎯 最佳实践

### 1. 工具命名规范

```
mcp/<category>/<action>

示例:
- mcp/weather/query
- mcp/database/select
- mcp/file/read
- mcp/camera/capture
```

### 2. 技能分类

```json
{
    "name": "skill_name",
    "description": "技能描述",
    "capabilities": ["能力1", "能力2"],
    "tools": ["依赖工具"]
}
```

### 3. 安全建议

- 数据库工具只允许SELECT
- 文件操作限制路径范围
- 网络请求设置超时
- 敏感操作需要验证

---

## 🔗 完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    启动MCP工具节点                            │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  1. 加载工具定义 (tools_file)                                │
│  2. 加载技能定义 (skills_file)                               │
│  3. 注册到本地工具表                                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  启动P2P网络                                                 │
│  - 监听端口                                                  │
│  - 连接Bootstrap节点                                         │
│  - 加入全局Topic                                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  广播心跳 (每15秒)                                           │
│  {                                                          │
│    "type": "muscle_announce",                               │
│    "node_id": "xxx",                                        │
│    "capabilities": ["mcp/tool1", "mcp/tool2"]               │
│  }                                                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  大脑节点发现并注册                                          │
│  - 更新肌肉节点注册表                                        │
│  - 记录能力列表                                              │
│  - 准备调用                                                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  等待调用                                                    │
│  - 接收MCP请求                                               │
│  - 执行本地工具                                              │
│  - 返回结果                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 💡 常见问题

### Q: 如何确认节点已被发现？

A: 查看大脑节点日志，会显示：
```
💪 发现肌肉节点: My-Service -> ['mcp/my_tool']
```

### Q: 如何测试工具是否可用？

A: 使用交互模式：
```bash
mcp-node> call mcp/my_tool {"arg": "value"}
```

### Q: 如何连接到远程网络？

A: 指定远程Bootstrap地址：
```bash
python run_mcp_node.py \
    --name MyNode \
    --bootstrap /ip4/远程IP/tcp/端口/p2p/节点ID
```

### Q: 如何查看网络中的所有节点？

A: 在大脑节点中：
```python
print(brain.crdt.muscle_registry)
print(brain.p2p.get_known_peers())
```
