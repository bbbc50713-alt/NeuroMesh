# 🌌 Agent P2P - 去中心化多智能体协作网络

基于 **MCP+ SKILLS + libp2p + CRDT** 的下一代 AI 智能体协作操作系统。

---

## 📖 目录

- [项目简介](#项目简介)
- [核心特点](#核心特点)
- [解决的问题](#解决的问题)
- [技术优势](#技术优势)
- [技术架构](#技术架构)
- [核心方案](#核心方案)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [未来展望](#未来展望)
- [演进路线](#演进路线)

---

## 项目简介

Agent P2P 是一个**去中心化的多智能体协作网络**，旨在解决当前 AI Agent 系统面临的中心化瓶颈、单点故障、数据隐私和算力成本等核心问题。

本项目将 **MCP (Model Context Protocol)** 协议与 **libp2p** P2P 网络深度融合，利用 **CRDT (无冲突复制数据类型)** 实现真正的分布式状态一致性，构建了一个"无主化、自愈性、液态算力"的智能体协作平台。

```
┌─────────────────────────────────────────────────────────────┐
│                     中心服务器 (可选)                         │
│              Bootstrap + 持久化 + CRDT合并                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
   ┌────┴────┐        ┌────┴────┐        ┌────┴────┐
   │ Agent A │◄──────►│ Agent B │◄──────►│ Agent C │
   │ CRDT    │  P2P   │ CRDT    │  P2P   │ CRDT    │
   │ MCP     │        │ MCP     │        │ MCP     │
   └─────────┘        └─────────┘        └─────────┘
```

---

## 核心特点

### 🔄 CRDT 无冲突合并
- 基于 **Lamport Clock** 的真正无冲突数据类型
- 解决分布式系统中的时钟同步和并发冲突问题
- 保证数据最终一致性，无需中心化锁

### 🌐 P2P 去中心化通信
- 基于 **libp2p + GossipSub** 实现去中心化消息传播
- 支持 NAT 穿透、多路复用、节点发现
- 无单点故障，网络自愈

### 🔌 MCP 协议标准化
- 工具发现和跨节点调用标准化
- 将 MCP 从本地 stdio/HTTP 升级到 P2P Stream
- 实现技能(Skills)的去中心化共享

### ⚡ 任务抢占与调度
- 租约机制实现去中心化任务调度
- 自动检测死节点并回收任务
- 备份广播确保任务状态实时同步

### 🧠 脑手分离架构
- **Brain Node**: 挂载 LLM，负责推理、规划、调度
- **Muscle Node**: 极轻量执行节点，负责物理操作
- 算力液态池化，成本指数级下降

### 🔒 公私域隔离
- 公网大厅：任务发布、状态同步、心跳广播
- 私有子网：高频协作、敏感数据传输、执行细节
- 防止广播风暴，保护数据隐私

---

## 解决的问题

### 1. 中心化瓶颈
| 传统方案 | 本项目方案 |
|---------|-----------|
| 依赖中心服务器调度 | P2P 网络无主调度 |
| 服务器宕机全系统瘫痪 | 任意节点可接管任务 |
| 网络延迟集中爆发 | 边缘计算就近执行 |

### 2. 数据一致性问题
| 传统方案 | 本项目方案 |
|---------|-----------|
| Redis 分布式锁 | CRDT 数学级无冲突 |
| 时间戳覆盖冲突 | Lamport Clock + NodeID |
| 网络分区数据分裂 | 自动合并，最终一致 |

### 3. 算力成本问题
| 传统方案 | 本项目方案 |
|---------|-----------|
| 每个节点都需要 LLM | Brain/Muscle 分离 |
| 昂贵的 GPU 算力 | 轻量节点仅执行 |
| 资源利用率低 | 算力液态池化 |

### 4. 数据安全问题
| 传统方案 | 本项目方案 |
|---------|-----------|
| 敏感数据全网广播 | 私有子网隔离 |
| AI 可执行任意操作 | 物理级安全隔离 |
| 无权限边界 | Muscle 节点本地防御 |

### 5. 任务黑洞问题
| 传统方案 | 本项目方案 |
|---------|-----------|
| 节点宕机任务丢失 | 租约超时自动回收 |
| 无备份机制 | CRDT 全网冗余 |
| 需人工干预 | 系统自愈恢复 |

---

## 技术优势

### 🚀 架构先进性

```
传统 Agent 系统:
┌─────────────┐
│  中心服务器   │ ← 单点故障
│  (调度+存储)  │ ← 瓶颈
└──────┬──────┘
       │
  ┌────┴────┐
  │ Agents  │ ← 被动执行
  └─────────┘

本项目架构:
┌───────────────────────────────────────┐
│           P2P 网络 (libp2p)            │
│  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐   │
│  │Brain│◄─►│Brain│◄─►│Muscle│◄─►│Muscle│ │
│  │ LLM │  │ LLM │  │轻量  │  │轻量  │   │
│  └─────┘  └─────┘  └─────┘  └─────┘   │
│       ↓ CRDT 同步 ↓                    │
│       └── 无主调度 ──┘                  │
└───────────────────────────────────────┘
```

### 💰 成本对比

| 场景 | 传统方案 | 本项目方案 | 节省 |
|-----|---------|-----------|-----|
| 10个节点 | 10个 LLM API | 2个 LLM + 8个轻量节点 | 80% |
| 数据库访问 | AI 直连 | Muscle 隔离 | 安全性↑ |
| 宕机恢复 | 人工介入 | 自动接管 | 99.9% SLA |

### 🛡 安全性

- **物理隔离**: Muscle 节点可本地拦截危险操作
- **私有通道**: 敏感数据不在公网传输
- **无中心**: 没有单一攻击目标

---

## 技术架构

### 核心技术栈

| 模块 | 技术选型 | 选型理由 |
|:---|:---|:---|
| **底层网络** | `py-libp2p` | 原生支持 NAT 穿透、GossipSub、多路复用 |
| **通信协议** | GossipSub | 节省带宽，适合大规模 Agent 集群 |
| **状态同步** | 自研 CvRDT | Lamport Clock + LWW Register，极致可控 |
| **工具协议** | MCP over libp2p | 将 MCP 传输层升级为 P2P Stream |
| **中心兜底** | FastAPI + SQLite | Bootstrap + 冷数据持久化 |
| **AI 引擎** | LiteLLM / OpenAI | 通过 MCP 协议感知工具 |

### 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                      应用层 (Application)                    │
│         Brain Node (LLM)     │     Muscle Node (Tools)      │
├─────────────────────────────────────────────────────────────┤
│                      协议层 (Protocol)                       │
│              MCP (Model Context Protocol)                   │
│         工具发现 │ 工具调用 │ 技能共享 │ 任务委派              │
├─────────────────────────────────────────────────────────────┤
│                      状态层 (State)                         │
│                    CRDT Engine                              │
│      Lamport Clock │ LWW Register │ 状态合并 │ 冲突解决       │
├─────────────────────────────────────────────────────────────┤
│                      网络层 (Network)                       │
│                    libp2p + GossipSub                       │
│    PubSub 广播 │ Stream RPC │ NAT 穿透 │ 节点发现            │
└─────────────────────────────────────────────────────────────┘
```

### 节点角色

#### 🧠 Brain Node (大脑节点)
```python
特征:
- 挂载 LLM (OpenAI/Claude/本地模型)
- 具备推理、规划、调度能力
- 订阅全局 TodoList

职责:
- 任务抢占与分解
- 私有子网管理
- 肌肉节点调用
- 人机交互
```

#### 💪 Muscle Node (肌肉节点)
```python
特征:
- 无 LLM，极轻量 (几十MB内存)
- 可部署在树莓派、旧手机、IoT设备
- 只暴露 MCP 工具接口

职责:
- 物理执行 (拍照、数据库查询、硬件控制)
- 响应 Brain 节点的 RPC 调用
- 心跳广播存在
```

---

## 核心方案

### 1. CRDT 状态引擎

```python
# 真正的 CRDT: Lamport Clock + NodeID
class CRDTStateEngine:
    def merge(self, remote_todo):
        # 比较规则:
        # 1. 逻辑时钟大的胜出
        # 2. 时钟相同，NodeID 字典序大的胜出
        if remote_todo["v_time"] > local["v_time"]:
            return remote_todo  # 远程胜出
        elif remote_todo["v_time"] == local["v_time"]:
            if remote_todo["v_node"] > local["v_node"]:
                return remote_todo  # 字典序打破平局
        return local
```

### 2. 任务抢占与租约机制

```python
# 去中心化调度: 租约 + 软备份
def attempt_lock(task_id, lease_duration=300):
    task = todos[task_id]
    now = time.time()
    
    # 条件: pending 或 租约过期(死节点恢复)
    if task["status"] == "pending" or \
       (task["status"] == "locked" and now > task["lease_expiry"]):
        task["status"] = "locked"
        task["assignee"] = my_node_id
        task["lease_expiry"] = now + lease_duration
        return True
    return False
```

### 3. 公私域隔离

```
公网大厅 (Global PubSub):
├── 任务发布与状态变更
├── 节点心跳广播
└── 聊天室消息

私有子网 (Private Subnet):
├── 高频协作对话
├── 敏感数据传输
├── 大文件分块传输
└── 任务执行细节
```

### 4. MCP over libp2p

```python
# 传统 MCP: Claude -> stdio/HTTP -> Tool
# 融合 MCP: Agent A -> libp2p Stream -> Agent B (Tool Provider)

async def call_remote_mcp(target_node, tool_name, arguments):
    # 1. 建立 P2P Stream
    stream = await host.connect(target_node).open_stream("/mcp/1.0")
    
    # 2. 发送 JSON-RPC 请求
    request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }
    await stream.write(json.dumps(request).encode())
    
    # 3. 接收响应
    result = await stream.read()
    return json.loads(result)
```

---

## 快速开始

### 安装依赖

```bash
# 核心依赖
pip install fastapi uvicorn httpx pydantic

# P2P 网络 (推荐)
pip install libp2p multiaddr

# LLM 支持 (可选)
pip install openai litellm
```

### 启动中心服务器 (可选)

```bash
python run_server.py --port 8000
```

### 启动 Brain 节点

```bash
# 启动第一个 Brain
python run_brain.py --name Brain-A --port 10000

# 启动第二个 Brain (连接到第一个)
python run_brain.py --name Brain-B --port 10001 \
    --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/<Brain-A的PeerID>
```

### 启动 Muscle 节点

```bash
# 摄像头肌肉节点
python run_muscle.py --type camera --name Muscle-Camera --port 10010

# 数据库肌肉节点
python run_muscle.py --type database --name Muscle-DB --port 10011
```

### 运行测试

```bash
python test_mvp.py
```

---

## 项目结构

```
Agent_libp2p/
├── core/                       # 核心模块
│   ├── crdt_engine.py          # CRDT 引擎 (Lamport Clock + LWW)
│   ├── crdt_engine_v2.py       # 增强版 CRDT (支持聊天室)
│   ├── mcp_protocol.py         # MCP 工具协议
│   ├── mcp_client.py           # MCP 客户端管理
│   ├── mcp_manager.py          # MCP 服务配置管理
│   ├── skills_manager.py       # 技能管理
│   ├── skill_loader.py         # 技能加载器 (渐进式加载)
│   └── remote_resource_manager.py  # 远程资源管理
│
├── network/                    # 网络层
│   └── p2p_network.py          # P2P 网络 (libp2p + GossipSub)
│
├── agent/                      # Agent 节点
│   ├── agent_node.py           # Agent 核心逻辑
│   ├── brain_node.py           # 大脑节点 (LLM + 决策)
│   └── muscle_node.py          # 肌肉节点 (纯执行)
│
├── server/                     # 中心服务器
│   └── central_server.py       # 兜底服务器
│
├── examples/                   # 示例
│   ├── mcp_tools_example.py    # MCP 工具示例
│   ├── skills_config.json      # 技能配置
│   └── MCP_NODE_GUIDE.md       # MCP 节点指南
│
├── run_agent.py                # 启动 Agent
├── run_brain.py                # 启动 Brain 节点
├── run_muscle.py               # 启动 Muscle 节点
├── run_server.py               # 启动服务器
├── test_mvp.py                 # MVP 测试
├── streamlit_app.py            # Web UI
└── terminal_ui.py              # 终端 UI
```

---

## 未来展望

### 🌐 去中心化技能市场 (Phase 4)

```
┌─────────────────────────────────────────────────────┐
│              去中心化技能市场                         │
│                                                     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐        │
│  │ Skill A │    │ Skill B │    │ Skill C │        │
│  │ 图像处理 │    │ 数据分析 │    │ 代码生成 │        │
│  │ $0.01/次│    │ $0.02/次│    │ $0.05/次│        │
│  └────┬────┘    └────┬────┘    └────┬────┘        │
│       │              │              │              │
│       └──────────────┼──────────────┘              │
│                      │                             │
│              ┌───────┴───────┐                     │
│              │  技能发现协议   │                     │
│              │  声誉系统      │                     │
│              │  自动定价      │                     │
│              └───────────────┘                     │
└─────────────────────────────────────────────────────┘
```

### 🔗 跨设备协同

- **Windows/Mac**: 运行 Brain 节点，负责大模型推理
- **树莓派**: 运行 Muscle 节点，提供硬件接口
- **云服务器**: 提供联网检索、数据库服务
- **旧手机**: 提供传感器、摄像头能力

### 🤖 群体智能 (Swarm Intelligence)

```
任务: "分析 Q3 财报并生成报告"

Brain-A: 抢占任务 → 分解子任务
    ├── Muscle-Web: 抓取财报数据
    ├── Brain-B: 分析数据趋势
    ├── Muscle-Chart: 生成图表
    └── Brain-C: 撰写报告
```

### 🛡 安全增强

- TLS + Ed25519 密钥对验证
- 操作签名与审计日志
- 白名单访问控制

---

## 演进路线

### ✅ Phase 1: 协作基础层 (已完成)
- [x] 基于 libp2p 的 P2P 通信
- [x] Lamport Clock CRDT 引擎
- [x] 多 Agent TodoList 协作
- [x] 简易聊天室融合

### 🚀 Phase 2: 算力调度层 (当前)
- [x] Brain/Muscle 节点分离
- [x] MCP over libp2p Stream
- [x] 远程资源发现与调用
- [ ] 渐进式 Skill 加载优化

### 🛡 Phase 3: 隐私与容错层
- [ ] 任务租约与超时抢占
- [ ] 私有子网隔离
- [ ] 混沌工程测试
- [ ] 安全认证机制

### 🌐 Phase 4: 终极形态
- [ ] 去中心化技能市场
- [ ] 合同网协议 (Contract Net)
- [ ] Web3 身份认证
- [ ] 跨组织协作

---

## MVP 验证点

| 功能 | 状态 | 说明 |
|-----|------|-----|
| 多智能体协作 | ✅ | 两个 Agent 可共同操作 todolist |
| 数据一致性 | ✅ | CRDT 保证最终一致性 |
| 任务抢占 | ✅ | 自动抢占 pending 任务 |
| 失败恢复 | ✅ | 节点宕机后任务自动恢复 |
| 备份广播 | ✅ | 任务状态变更实时广播 |
| 脑手分离 | ✅ | Brain/Muscle 角色分离 |
| 私有子网 | ✅ | 任务执行隔离 |

---

## API 示例

```python
from agent.brain_node import BrainNode, BrainConfig

# 创建 Brain 节点
config = BrainConfig(
    name="MyBrain",
    port=10000,
    llm_base_url="https://api.openai.com/v1",
    llm_api_key="api_xxxxxxxx_xxxx",
    mounted_mcps=["filesystem"],
    mounted_skills=["web-search"]
)

brain = BrainNode(config)
await brain.start()

# 创建任务
task = await brain.create_task(
    title="分析数据并生成报告",
    description="读取 /data 目录下的 CSV 文件，分析趋势，生成报告",
    priority=1
)

# Brain 自动:
# 1. 抢占任务
# 2. LLM 分析选择工具
# 3. 调用本地或远程 Muscle 执行
# 4. 返回结果
```

---

## 贡献指南

欢迎贡献代码、提出问题或建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 致谢

- [libp2p](https://libp2p.io/) - 模块化网络栈
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Python Web 框架

---

<p align="center">
  <b>构建下一代去中心化 AI 协作网络</b>
</p>
