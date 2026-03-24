"""
Streamlit 节点UI界面 - 多Agent协作管理

功能:
1. 创建和管理多个节点（Brain/Muscle）
2. 查看在线节点和协作状态
3. 管理Todolist（创建、查看、删除任务）
4. 支持多节点协作
5. MCP配置管理
6. Skills管理
"""

import streamlit as st
import asyncio
import os
import sys
import time
import threading
import json
from typing import Dict, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.brain_node import BrainNode, BrainConfig
from agent.muscle_node import MuscleNode, MuscleConfig
from core.crdt_engine_v2 import TaskState
from core.mcp_manager import MCPManager, MCPServerConfig, create_mcp_config_from_template
from core.skills_manager import SkillManager, SkillConfig


st.set_page_config(
    page_title="Agent P2P 节点管理",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


_node_loops: Dict[str, asyncio.AbstractEventLoop] = {}
_node_threads: Dict[str, threading.Thread] = {}


def init_session_state():
    if "nodes" not in st.session_state:
        st.session_state.nodes: Dict[str, dict] = {}
    if "tasks" not in st.session_state:
        st.session_state.tasks: Dict[str, dict] = {}
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages: List[dict] = []
    if "mcp_manager" not in st.session_state:
        st.session_state.mcp_manager = MCPManager()
    if "skill_manager" not in st.session_state:
        st.session_state.skill_manager = SkillManager()


def run_async_in_thread(coro, node_name):
    """在新线程中运行异步任务"""
    global _node_loops
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _node_loops[node_name] = loop
    try:
        loop.run_until_complete(coro)
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()
        if node_name in _node_loops:
            del _node_loops[node_name]


def create_brain_node_sync(name: str, port: int = 0, llm_base_url: str = "", 
                            llm_api_key: str = "", llm_model: str = "gpt-4",
                            mounted_mcps: List[str] = None, mounted_skills: List[str] = None):
    """同步方式创建Brain节点"""
    global _node_threads
    config = BrainConfig(
        name=name, 
        port=port,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        mounted_mcps=mounted_mcps or [],
        mounted_skills=mounted_skills or []
    )
    node = BrainNode(config)
    
    async def start_node():
        await node.start()
        while node._running:
            await asyncio.sleep(1)
    
    thread = threading.Thread(
        target=run_async_in_thread,
        args=(start_node(), name),
        daemon=True
    )
    thread.start()
    _node_threads[name] = thread
    
    time.sleep(0.5)
    
    return node


def create_muscle_node_sync(name: str, port: int = 0, tools: List[str] = None,
                            mounted_skills: List[str] = None, mounted_mcps: List[str] = None):
    """同步方式创建Muscle节点"""
    global _node_threads
    config = MuscleConfig(
        name=name, 
        port=port,
        mounted_skills=mounted_skills or [],
        mounted_mcps=mounted_mcps or []
    )
    node = MuscleNode(config)
    
    async def start_node():
        await node.start()
        if tools:
            for tool in tools:
                async def default_handler(args: Dict) -> Dict:
                    return {
                        "status": "success",
                        "tool": tool,
                        "args": args,
                        "message": f"Tool {tool} executed successfully"
                    }
                node.register_tool(
                    name=tool,
                    handler=default_handler,
                    description=f"Default handler for {tool}"
                )
        while node._running:
            await asyncio.sleep(1)
    
    thread = threading.Thread(
        target=run_async_in_thread,
        args=(start_node(), name),
        daemon=True
    )
    thread.start()
    _node_threads[name] = thread
    
    time.sleep(0.5)
    
    return node


def stop_node_sync(node, node_name):
    """同步方式停止节点"""
    global _node_loops, _node_threads
    node._running = False
    if node_name in _node_loops:
        loop = _node_loops[node_name]
        if not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
    if node_name in _node_threads:
        del _node_threads[node_name]


def get_task_status_icon(state: str, is_deleted: bool = False) -> str:
    """获取任务状态图标"""
    if is_deleted:
        return "🗑️"
    return {
        TaskState.PENDING.value: "⏳",
        TaskState.LOCKED.value: "🔒",
        TaskState.IN_PROGRESS.value: "🔄",
        TaskState.DONE.value: "✅",
        TaskState.DELETED.value: "🗑️"
    }.get(state, "❓")


def main():
    init_session_state()
    
    st.title("🤖 Agent P2P 节点管理界面")
    st.markdown("---")
    
    with st.sidebar:
        st.header("📋 导航")
        page = st.radio(
            "选择页面",
            ["🏠 首页", "🧠 节点管理", "📝 任务管理", "💬 聊天室", "📊 协作状态", "🔌 MCP管理", "🎯 Skills管理"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        st.header("⚡ 快速操作")
        
        with st.expander("➕ 创建节点", expanded=False):
            node_type = st.selectbox("节点类型", ["Brain (决策节点)", "Muscle (执行节点)"])
            node_name = st.text_input("节点名称", value=f"Node-{len(st.session_state.nodes)+1}")
            
            if node_type == "Brain (决策节点)":
                st.markdown("**LLM 配置**")
                llm_base_url = st.text_input("LLM Base URL", value="", placeholder="https://api.openai.com/v1")
                llm_api_key = st.text_input("LLM API Key", value="", type="password")
                llm_model = st.text_input("LLM Model", value="gpt-4")
                
                st.markdown("**挂载配置**")
                mcp_manager = st.session_state.mcp_manager
                skill_manager = st.session_state.skill_manager
                
                available_mcps = list(mcp_manager.get_mountable_servers().keys())
                available_skills = [s for s in skill_manager.list_skills().keys() if skill_manager.get_skill(s).enabled]
                
                mounted_mcps = st.multiselect("挂载 MCP", available_mcps)
                mounted_skills = st.multiselect("挂载 Skills", available_skills)
            else:
                muscle_tools = st.text_input("工具列表 (逗号分隔)", value="mcp/tool1,mcp/tool2")
                
                st.markdown("**挂载配置**")
                mcp_manager = st.session_state.mcp_manager
                skill_manager = st.session_state.skill_manager
                
                available_mcps = list(mcp_manager.get_mountable_servers().keys())
                available_skills = [s for s in skill_manager.list_skills().keys() if skill_manager.get_skill(s).enabled]
                
                muscle_mounted_mcps = st.multiselect("挂载 MCP", available_mcps, key="muscle_mcps")
                muscle_mounted_skills = st.multiselect("挂载 Skills", available_skills, key="muscle_skills")
            
            if st.button("🚀 创建节点", use_container_width=True):
                if node_name and node_name not in st.session_state.nodes:
                    try:
                        if "Brain" in node_type:
                            node = create_brain_node_sync(
                                name=node_name,
                                llm_base_url=llm_base_url,
                                llm_api_key=llm_api_key,
                                llm_model=llm_model,
                                mounted_mcps=mounted_mcps,
                                mounted_skills=mounted_skills
                            )
                            st.session_state.nodes[node_name] = {
                                "node": node,
                                "type": "brain",
                                "llm_configured": bool(llm_base_url and llm_api_key),
                                "mounted_mcps": mounted_mcps,
                                "mounted_skills": mounted_skills,
                                "created_at": datetime.now()
                            }
                        else:
                            tools = [t.strip() for t in muscle_tools.split(",") if t.strip()]
                            node = create_muscle_node_sync(
                                node_name, 
                                tools=tools,
                                mounted_skills=muscle_mounted_skills,
                                mounted_mcps=muscle_mounted_mcps
                            )
                            st.session_state.nodes[node_name] = {
                                "node": node,
                                "type": "muscle",
                                "tools": tools,
                                "mounted_skills": muscle_mounted_skills,
                                "mounted_mcps": muscle_mounted_mcps,
                                "created_at": datetime.now()
                            }
                        
                        st.success(f"✅ 节点 {node_name} 创建成功!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 创建失败: {e}")
                else:
                    st.warning("⚠️ 节点名称已存在或为空")
    
    if page == "🏠 首页":
        render_home_page()
    elif page == "🧠 节点管理":
        render_nodes_page()
    elif page == "📝 任务管理":
        render_tasks_page()
    elif page == "💬 聊天室":
        render_chat_page()
    elif page == "📊 协作状态":
        render_collab_page()
    elif page == "🔌 MCP管理":
        render_mcp_page()
    elif page == "🎯 Skills管理":
        render_skills_page()


def render_home_page():
    """渲染首页"""
    st.header("🏠 系统概览")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        brain_count = sum(1 for n in st.session_state.nodes.values() if n["type"] == "brain")
        st.metric("🧠 Brain节点", brain_count)
    
    with col2:
        muscle_count = sum(1 for n in st.session_state.nodes.values() if n["type"] == "muscle")
        st.metric("💪 Muscle节点", muscle_count)
    
    with col3:
        total_tasks = 0
        for node_info in st.session_state.nodes.values():
            if node_info["type"] == "brain":
                node = node_info["node"]
                total_tasks += len(node.crdt.get_all_tasks())
        st.metric("📝 总任务数", total_tasks)
    
    with col4:
        mcp_count = len(st.session_state.mcp_manager.list_servers())
        skills_count = len(st.session_state.skill_manager.list_skills())
        st.metric("🔌 MCP/Skills", f"{mcp_count}/{skills_count}")
    
    st.markdown("---")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("📡 在线节点")
        if st.session_state.nodes:
            for name, node_info in st.session_state.nodes.items():
                node_type = "🧠 Brain" if node_info["type"] == "brain" else "💪 Muscle"
                created = node_info["created_at"].strftime("%H:%M:%S")
                
                with st.container():
                    st.markdown(f"**{node_type}**: `{name}`")
                    st.caption(f"创建时间: {created}")
                    
                    if node_info["type"] == "brain":
                        node = node_info["node"]
                        status = node.get_status()
                        st.caption(f"状态: {status['state']} | 任务: {len(node.crdt.get_all_tasks())}")
                    else:
                        tools = node_info.get("tools", [])
                        st.caption(f"工具: {len(tools)}")
                    
                    st.markdown("---")
        else:
            st.info("暂无在线节点，请在左侧创建节点")
    
    with col_right:
        st.subheader("📝 最近任务")
        recent_tasks = []
        for node_info in st.session_state.nodes.values():
            if node_info["type"] == "brain":
                node = node_info["node"]
                for task_id in node.crdt.get_all_tasks():
                    task = node.crdt.tasks.get(task_id)
                    if task and not task.is_deleted:
                        recent_tasks.append({
                            "id": task_id,
                            "title": task.metadata.title,
                            "state": task.state,
                            "creator": task.metadata.creator
                        })
        
        if recent_tasks:
            for task in recent_tasks[:5]:
                icon = get_task_status_icon(task["state"])
                st.markdown(f"{icon} **{task['title']}**")
                st.caption(f"ID: {task['id'][:12]}... | 创建者: {task['creator']}")
                st.markdown("---")
        else:
            st.info("暂无任务")


def render_nodes_page():
    """渲染节点管理页面"""
    st.header("🧠 节点管理")
    
    tab1, tab2 = st.tabs(["Brain节点", "Muscle节点"])
    
    with tab1:
        st.subheader("🧠 Brain节点列表")
        brain_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "brain"}
        
        if brain_nodes:
            for name, node_info in brain_nodes.items():
                node = node_info["node"]
                status = node.get_status()
                
                with st.expander(f"🧠 {name}", expanded=True):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("状态", status["state"])
                    with col2:
                        st.metric("任务数", len(node.crdt.get_all_tasks()))
                    with col3:
                        st.metric("活跃节点", len(status.get("known_peers", [])))
                    
                    st.markdown("**任务统计:**")
                    stats = node.crdt.get_stats()
                    cols = st.columns(5)
                    cols[0].metric("待处理", stats.get("pending", 0))
                    cols[1].metric("已锁定", stats.get("locked", 0))
                    cols[2].metric("执行中", stats.get("in_progress", 0))
                    cols[3].metric("已完成", stats.get("done", 0))
                    cols[4].metric("已删除", stats.get("deleted", 0))
                    
                    st.markdown("**Skills 渐进式加载:**")
                    skill_stats = status.get("skill_stats", {})
                    cols = st.columns(4)
                    cols[0].metric("已注册", skill_stats.get("total_skills", 0))
                    cols[1].metric("已加载", skill_stats.get("loaded_skills", 0))
                    cols[2].metric("工具数", skill_stats.get("total_tools", 0))
                    cols[3].metric("最大加载数", skill_stats.get("max_loaded", 20))
                    
                    st.markdown("**远程资源:**")
                    remote_stats = status.get("remote_stats", {})
                    cols = st.columns(4)
                    cols[0].metric("远程Skills", remote_stats.get("remote_skills", 0))
                    cols[1].metric("远程MCPs", remote_stats.get("remote_mcps", 0))
                    cols[2].metric("远程工具", remote_stats.get("remote_tools", 0))
                    cols[3].metric("待处理请求", remote_stats.get("pending_requests", 0))
                    
                    active_mcps = status.get("active_mcps", [])
                    if active_mcps:
                        st.markdown(f"**活跃 MCP:** {', '.join(active_mcps)}")
                    
                    if st.button(f"🛑 停止节点 {name}", key=f"stop_{name}"):
                        try:
                            stop_node_sync(node, name)
                            del st.session_state.nodes[name]
                            st.success(f"✅ 节点 {name} 已停止")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 停止失败: {e}")
        else:
            st.info("暂无Brain节点，请在左侧创建")
    
    with tab2:
        st.subheader("💪 Muscle节点列表")
        muscle_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "muscle"}
        
        if muscle_nodes:
            for name, node_info in muscle_nodes.items():
                with st.expander(f"💪 {name}", expanded=True):
                    node = node_info["node"]
                    
                    st.markdown("**可用工具:**")
                    tools = node_info.get("tools", [])
                    if tools:
                        for tool in tools:
                            st.code(tool, language=None)
                    else:
                        st.info("无注册工具")
                    
                    if hasattr(node, 'get_status'):
                        status = node.get_status()
                        
                        st.markdown("**Skills:**")
                        skill_stats = status.get("skill_stats", {})
                        cols = st.columns(3)
                        cols[0].metric("已注册", skill_stats.get("total_skills", 0))
                        cols[1].metric("已加载", skill_stats.get("loaded_skills", 0))
                        cols[2].metric("工具数", skill_stats.get("total_tools", 0))
                        
                        st.markdown(f"**MCP:** {status.get('mcp_count', 0)} 个")
                        
                        mounted_skills = status.get("mounted_skills", [])
                        if mounted_skills:
                            st.markdown(f"**挂载 Skills:** {', '.join(mounted_skills)}")
                        
                        mounted_mcps = status.get("mounted_mcps", [])
                        if mounted_mcps:
                            st.markdown(f"**挂载 MCP:** {', '.join(mounted_mcps)}")
                    
                    if st.button(f"🛑 停止节点 {name}", key=f"stop_muscle_{name}"):
                        try:
                            stop_node_sync(node_info["node"], name)
                            del st.session_state.nodes[name]
                            st.success(f"✅ 节点 {name} 已停止")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 停止失败: {e}")
        else:
            st.info("暂无Muscle节点，请在左侧创建")


def render_tasks_page():
    """渲染任务管理页面"""
    st.header("📝 任务管理")
    
    brain_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "brain"}
    
    if not brain_nodes:
        st.warning("⚠️ 请先创建Brain节点")
        return
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📋 任务列表")
        
        selected_node = st.selectbox("选择节点", list(brain_nodes.keys()))
        node = brain_nodes[selected_node]["node"]
        
        tasks = node.crdt.get_all_tasks()
        if tasks:
            for task_id in tasks:
                task = node.crdt.tasks.get(task_id)
                if not task:
                    continue
                
                icon = get_task_status_icon(task.state, task.is_deleted)
                
                with st.container():
                    st.markdown(f"### {icon} {task.metadata.title}")
                    
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.caption(f"**ID:** `{task_id[:16]}...`")
                    with col_b:
                        st.caption(f"**创建者:** {task.metadata.creator}")
                    with col_c:
                        st.caption(f"**状态:** {task.state}")
                    
                    if task.is_deleted:
                        st.caption(f"🗑️ 已删除 by {task.deleted_by} at {datetime.fromtimestamp(task.deleted_at).strftime('%H:%M:%S')}")
                    
                    if task.state == TaskState.DONE.value and not task.is_deleted:
                        if st.button(f"🗑️ 删除任务", key=f"del_{task_id}"):
                            success, msg = node.crdt.delete_task(task_id)
                            if success:
                                st.success(f"✅ {msg}")
                                st.rerun()
                            else:
                                st.error(f"❌ {msg}")
                    
                    st.markdown("---")
        else:
            st.info("暂无任务")
    
    with col2:
        st.subheader("➕ 创建任务")
        
        task_title = st.text_input("任务标题")
        task_creator = st.text_input("创建者", value=selected_node)
        task_node = st.selectbox("创建到节点", list(brain_nodes.keys()), key="create_node_select")
        
        if st.button("📝 创建任务", use_container_width=True):
            if task_title:
                try:
                    target_node = brain_nodes[task_node]["node"]
                    task = target_node.crdt.create_task(
                        title=task_title,
                        creator=task_creator
                    )
                    st.success(f"✅ 任务创建成功: {task.id[:12]}...")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 创建失败: {e}")
            else:
                st.warning("⚠️ 请输入任务标题")


def render_chat_page():
    """渲染聊天室页面"""
    st.header("💬 聊天室")
    
    brain_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "brain"}
    
    if not brain_nodes:
        st.warning("⚠️ 请先创建Brain节点")
        return
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("📨 消息记录")
        
        chat_container = st.container()
        with chat_container:
            if st.session_state.chat_messages:
                for msg in st.session_state.chat_messages[-20:]:
                    time_str = datetime.fromtimestamp(msg["time"]).strftime("%H:%M:%S")
                    st.markdown(f"**[{time_str}] {msg['sender']}:** {msg['content']}")
            else:
                st.info("暂无消息")
    
    with col2:
        st.subheader("📤 发送消息")
        
        sender_node = st.selectbox("发送节点", list(brain_nodes.keys()))
        message = st.text_area("消息内容")
        related_task = st.text_input("关联任务ID (可选)")
        
        if st.button("📨 发送", use_container_width=True):
            if message:
                st.session_state.chat_messages.append({
                    "sender": sender_node,
                    "content": message,
                    "time": time.time(),
                    "task_id": related_task
                })
                st.success("✅ 消息已发送")
                st.rerun()
            else:
                st.warning("⚠️ 请输入消息内容")


def render_collab_page():
    """渲染协作状态页面"""
    st.header("📊 协作状态")
    
    brain_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "brain"}
    muscle_nodes = {k: v for k, v in st.session_state.nodes.items() if v["type"] == "muscle"}
    
    st.subheader("🌐 网络拓扑")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🧠 Brain节点")
        if brain_nodes:
            for name, node_info in brain_nodes.items():
                node = node_info["node"]
                status = node.get_status()
                
                st.markdown(f"""
                ```
                ┌─────────────────────────────┐
                │ 🧠 {name:^23} │
                ├─────────────────────────────┤
                │ 状态: {status['state']:<21} │
                │ 任务: {len(node.crdt.get_all_tasks()):<21} │
                │ 活跃节点: {len(status.get('known_peers', [])):<17} │
                └─────────────────────────────┘
                ```
                """)
        else:
            st.info("无Brain节点")
    
    with col2:
        st.markdown("### 💪 Muscle节点")
        if muscle_nodes:
            for name, node_info in muscle_nodes.items():
                tools = node_info.get("tools", [])
                st.markdown(f"""
                ```
                ┌─────────────────────────────┐
                │ 💪 {name:^23} │
                ├─────────────────────────────┤
                │ 工具数: {len(tools):<20} │
                └─────────────────────────────┘
                ```
                """)
        else:
            st.info("无Muscle节点")
    
    st.markdown("---")
    
    st.subheader("📈 协作统计")
    
    total_pending = 0
    total_locked = 0
    total_in_progress = 0
    total_done = 0
    total_deleted = 0
    
    for node_info in brain_nodes.values():
        stats = node_info["node"].crdt.get_stats()
        total_pending += stats.get("pending", 0)
        total_locked += stats.get("locked", 0)
        total_in_progress += stats.get("in_progress", 0)
        total_done += stats.get("done", 0)
        total_deleted += stats.get("deleted", 0)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("⏳ 待处理", total_pending)
    col2.metric("🔒 已锁定", total_locked)
    col3.metric("🔄 执行中", total_in_progress)
    col4.metric("✅ 已完成", total_done)
    col5.metric("🗑️ 已删除", total_deleted)
    
    st.markdown("---")
    
    st.subheader("🔧 可用工具 (来自Muscle节点)")
    all_tools = []
    for node_info in muscle_nodes.values():
        all_tools.extend(node_info.get("tools", []))
    
    if all_tools:
        cols = st.columns(min(len(all_tools), 4))
        for i, tool in enumerate(all_tools):
            cols[i % 4].code(tool, language=None)
    else:
        st.info("暂无可用工具，请创建Muscle节点并注册工具")


def render_mcp_page():
    """渲染MCP管理页面"""
    st.header("🔌 MCP管理")
    
    mcp_manager = st.session_state.mcp_manager
    
    tab1, tab2, tab3, tab4 = st.tabs(["📋 MCP列表", "➕ 添加MCP", "🔍 发现MCP", "🔗 挂载到节点"])
    
    with tab1:
        st.subheader("📋 已配置的MCP Server")
        servers = mcp_manager.list_servers()
        
        if servers:
            for name, config in servers.items():
                with st.expander(f"{'🔴' if config.disabled else '🟢'} {name}", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown(f"**命令:** `{config.command}`")
                        if config.args:
                            st.markdown(f"**参数:** `{' '.join(config.args)}`")
                        if config.env:
                            st.markdown("**环境变量:**")
                            st.json(config.env)
                    
                    with col2:
                        if config.disabled:
                            if st.button("✅ 启用", key=f"enable_{name}"):
                                mcp_manager.enable_server(name)
                                st.success(f"✅ 已启用 {name}")
                                st.rerun()
                        else:
                            if st.button("⏸️ 禁用", key=f"disable_{name}"):
                                mcp_manager.disable_server(name)
                                st.success(f"⏸️ 已禁用 {name}")
                                st.rerun()
                        
                        if st.button("🗑️ 删除", key=f"delete_{name}"):
                            mcp_manager.delete_server(name)
                            st.success(f"🗑️ 已删除 {name}")
                            st.rerun()
        else:
            st.info("暂无MCP配置，请在'添加MCP'标签页添加")
    
    with tab2:
        st.subheader("➕ 添加MCP Server")
        
        add_type = st.radio("添加方式", ["手动配置", "从JSON导入", "从Trae配置导入"])
        
        if add_type == "手动配置":
            col1, col2 = st.columns(2)
            
            with col1:
                mcp_name = st.text_input("MCP名称", placeholder="例如: filesystem")
                mcp_command = st.selectbox("命令", ["npx", "node", "python", "uvx", "其他"])
                if mcp_command == "其他":
                    mcp_command = st.text_input("自定义命令")
            
            with col2:
                mcp_args = st.text_area("参数 (每行一个)", placeholder="-y\n@modelcontextprotocol/server-filesystem")
                mcp_env = st.text_area("环境变量 (JSON格式)", placeholder='{"API_KEY": "api_xxxxxxxx_xxxx"}')
            
            if st.button("➕ 添加", use_container_width=True):
                if mcp_name and mcp_command:
                    args = [a.strip() for a in mcp_args.split("\n") if a.strip()]
                    env = {}
                    if mcp_env:
                        try:
                            env = json.loads(mcp_env)
                        except:
                            pass
                    
                    config = MCPServerConfig(command=mcp_command, args=args, env=env)
                    if mcp_manager.add_server(mcp_name, config):
                        st.success(f"✅ MCP {mcp_name} 添加成功!")
                        st.rerun()
                    else:
                        st.error(f"❌ MCP {mcp_name} 已存在")
                else:
                    st.warning("⚠️ 请填写MCP名称和命令")
        
        elif add_type == "从JSON导入":
            json_input = st.text_area("MCP配置 (JSON格式)", height=200, placeholder="""{
  "mcpServers": {
    "example-server": {
      "command": "npx",
      "args": ["-y", "mcp-server-example"]
    }
  }
}""")
            
            if st.button("📥 导入", use_container_width=True):
                try:
                    data = json.loads(json_input)
                    imported = 0
                    for name, server_data in data.get("mcpServers", {}).items():
                        config = MCPServerConfig.from_dict(server_data)
                        if mcp_manager.add_server(name, config):
                            imported += 1
                    st.success(f"✅ 成功导入 {imported} 个MCP")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 导入失败: {e}")
        
        elif add_type == "从Trae配置导入":
            trae_path = st.text_input("Trae配置文件路径", value=r"c:\Users\xiaobo\AppData\Roaming\Trae CN\User\mcp.json")
            
            if st.button("📥 导入", use_container_width=True):
                if os.path.exists(trae_path):
                    imported = mcp_manager.import_from_trae_config(trae_path)
                    st.success(f"✅ 成功导入 {imported} 个MCP")
                    st.rerun()
                else:
                    st.error(f"❌ 文件不存在: {trae_path}")
    
    with tab3:
        st.subheader("🔍 发现可用MCP")
        st.markdown("以下是常用的MCP Server，点击即可添加:")
        
        discovered = mcp_manager.discover_npx_mcp()
        
        cols = st.columns(3)
        for i, mcp in enumerate(discovered):
            with cols[i % 3]:
                with st.container():
                    st.markdown(f"**{mcp['name']}**")
                    st.caption(mcp['description'])
                    if st.button(f"➕ 添加", key=f"add_discovered_{mcp['name']}"):
                        config = MCPServerConfig(
                            command=mcp['command'],
                            args=mcp['args']
                        )
                        if mcp_manager.add_server(mcp['name'], config):
                            st.success(f"✅ 已添加 {mcp['name']}")
                            st.rerun()
                        else:
                            st.warning(f"⚠️ {mcp['name']} 已存在")
    
    with tab4:
        st.subheader("🔗 挂载MCP到节点")
        
        servers = mcp_manager.list_servers()
        nodes = st.session_state.nodes
        
        if not servers:
            st.warning("⚠️ 请先添加MCP")
            return
        
        if not nodes:
            st.warning("⚠️ 请先创建节点")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 选择MCP")
            mountable_servers = {n: s for n, s in servers.items() if not s.disabled}
            selected_mcp = st.selectbox("MCP Server", list(mountable_servers.keys()))
            
            if selected_mcp:
                server = servers[selected_mcp]
                st.markdown(f"**命令:** `{server.command}`")
                st.markdown(f"**已挂载到:** {', '.join(server.mounted_to) if server.mounted_to else '无'}")
        
        with col2:
            st.markdown("### 选择节点")
            node_type_filter = st.radio("节点类型", ["全部", "Brain", "Muscle"], horizontal=True)
            
            filtered_nodes = []
            for name, info in nodes.items():
                if node_type_filter == "全部" or \
                   (node_type_filter == "Brain" and info["type"] == "brain") or \
                   (node_type_filter == "Muscle" and info["type"] == "muscle"):
                    filtered_nodes.append(name)
            
            selected_node = st.selectbox("节点", filtered_nodes)
            
            if selected_node:
                node_info = nodes[selected_node]
                st.markdown(f"**类型:** {node_info['type']}")
        
        if st.button("🔗 挂载", use_container_width=True):
            if selected_mcp and selected_node:
                if mcp_manager.mount_to_node(selected_mcp, selected_node):
                    st.success(f"✅ 已将 {selected_mcp} 挂载到 {selected_node}")
                    st.rerun()
                else:
                    st.error("❌ 挂载失败")
        
        st.markdown("---")
        st.subheader("📋 挂载状态")
        
        mount_summary = mcp_manager.get_mount_summary()
        
        if mount_summary:
            for node_name, mcp_list in mount_summary.items():
                if node_name in nodes:
                    node_info = nodes[node_name]
                    st.markdown(f"**{node_name}** ({node_info['type']}):")
                    for mcp_name in mcp_list:
                        st.caption(f"  - {mcp_name}")
        else:
            st.info("暂无挂载关系")


def render_skills_page():
    """渲染Skills管理页面"""
    st.header("🎯 Skills管理")
    
    skill_manager = st.session_state.skill_manager
    
    tab1, tab2, tab3 = st.tabs(["📋 Skills列表", "➕ 添加Skill", "🔗 挂载到节点"])
    
    with tab1:
        st.subheader("📋 已配置的Skills")
        skills = skill_manager.list_skills()
        
        if skills:
            for name, config in skills.items():
                with st.expander(f"{'🔴' if not config.enabled else '🟢'} {name}", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown(f"**路径:** `{config.path}`")
                        st.markdown(f"**描述:** {config.description}")
                        st.markdown(f"**脚本:** {'✅' if config.has_script else '❌'}")
                        st.markdown(f"**MCP:** {'✅' if config.has_mcp else '❌'}")
                        if config.mounted_to:
                            st.markdown(f"**挂载到:** {', '.join(config.mounted_to)}")
                    
                    with col2:
                        if config.enabled:
                            if st.button("⏸️ 禁用", key=f"disable_skill_{name}"):
                                skill_manager.disable_skill(name)
                                st.success(f"⏸️ 已禁用 {name}")
                                st.rerun()
                        else:
                            if st.button("✅ 启用", key=f"enable_skill_{name}"):
                                skill_manager.enable_skill(name)
                                st.success(f"✅ 已启用 {name}")
                                st.rerun()
                        
                        if st.button("🔄 刷新", key=f"refresh_skill_{name}"):
                            skill_manager.refresh_skill_info(name)
                            st.success(f"🔄 已刷新 {name}")
                            st.rerun()
                        
                        if st.button("🗑️ 删除", key=f"delete_skill_{name}"):
                            skill_manager.delete_skill(name, remove_files=False)
                            st.success(f"🗑️ 已删除 {name}")
                            st.rerun()
        else:
            st.info("暂无Skills配置，请在'添加Skill'标签页添加")
    
    with tab2:
        st.subheader("➕ 添加Skill")
        
        add_type = st.radio("添加方式", ["创建新Skill", "从文件夹添加", "发现本地Skills"])
        
        if add_type == "创建新Skill":
            col1, col2 = st.columns(2)
            
            with col1:
                skill_name = st.text_input("Skill名称")
                skill_desc = st.text_area("描述")
            
            with col2:
                with_script = st.checkbox("包含script文件夹")
                with_mcp = st.checkbox("包含mcp文件夹")
            
            if st.button("➕ 创建", use_container_width=True):
                if skill_name:
                    if skill_manager.create_skill(skill_name, skill_desc, with_script, with_mcp):
                        st.success(f"✅ Skill {skill_name} 创建成功!")
                        st.rerun()
                    else:
                        st.error(f"❌ Skill {skill_name} 已存在")
                else:
                    st.warning("⚠️ 请填写Skill名称")
        
        elif add_type == "从文件夹添加":
            folder_path = st.text_input("Skill文件夹路径", placeholder="A:\\path\\to\\skill")
            copy_to_local = st.checkbox("复制到本地skills目录")
            
            if st.button("➕ 添加", use_container_width=True):
                if folder_path and os.path.isdir(folder_path):
                    skill_name = skill_manager.add_skill(folder_path, copy_to_local)
                    if skill_name:
                        st.success(f"✅ Skill {skill_name} 添加成功!")
                        st.rerun()
                    else:
                        st.error("❌ 添加失败，请确保文件夹包含skill.md文件")
                else:
                    st.warning("⚠️ 请输入有效的文件夹路径")
        
        elif add_type == "发现本地Skills":
            st.markdown("扫描本地skills目录和外部目录:")
            
            local_skills = skill_manager.discover_local_skills()
            st.markdown(f"**本地skills目录:** `{skill_manager.skills_dir}`")
            
            if local_skills:
                st.markdown("#### 发现的Skills:")
                for skill_path in local_skills:
                    skill_name = os.path.basename(skill_path)
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"📁 {skill_name}")
                    with col2:
                        existing = skill_manager.get_skill(skill_name)
                        if existing:
                            st.caption("已添加")
                        else:
                            if st.button("➕ 添加", key=f"add_local_{skill_name}"):
                                if skill_manager.add_skill(skill_path):
                                    st.success(f"✅ 已添加 {skill_name}")
                                    st.rerun()
            else:
                st.info("本地skills目录中没有发现新的Skills")
            
            st.markdown("---")
            external_dir = st.text_input("扫描外部目录", value=r"A:\StrategyFramework\clawdbot\moltbot\skills")
            
            if st.button("🔍 扫描"):
                if external_dir and os.path.isdir(external_dir):
                    external_skills = skill_manager.discover_skills_in_dir(external_dir)
                    if external_skills:
                        st.markdown(f"#### 在 {external_dir} 发现:")
                        for skill_path in external_skills:
                            skill_name = os.path.basename(skill_path)
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.markdown(f"📁 {skill_name}")
                            with col2:
                                if st.button("➕ 添加", key=f"add_ext_{skill_name}"):
                                    if skill_manager.add_skill(skill_path, copy_to_local=False):
                                        st.success(f"✅ 已添加 {skill_name}")
                                        st.rerun()
                    else:
                        st.info("该目录中没有发现有效的Skills")
                else:
                    st.warning("⚠️ 请输入有效的目录路径")
    
    with tab3:
        st.subheader("🔗 挂载Skills到节点")
        
        skills = skill_manager.list_skills()
        nodes = st.session_state.nodes
        
        if not skills:
            st.warning("⚠️ 请先添加Skills")
            return
        
        if not nodes:
            st.warning("⚠️ 请先创建节点")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 选择Skill")
            selected_skill = st.selectbox("Skill", [s for s in skills.keys() if skills[s].enabled])
            
            if selected_skill:
                skill = skills[selected_skill]
                st.markdown(f"**描述:** {skill.description}")
                st.markdown(f"**已挂载到:** {', '.join(skill.mounted_to) if skill.mounted_to else '无'}")
        
        with col2:
            st.markdown("### 选择节点")
            node_type_filter = st.radio("节点类型", ["全部", "Brain", "Muscle"], horizontal=True)
            
            filtered_nodes = []
            for name, info in nodes.items():
                if node_type_filter == "全部" or \
                   (node_type_filter == "Brain" and info["type"] == "brain") or \
                   (node_type_filter == "Muscle" and info["type"] == "muscle"):
                    filtered_nodes.append(name)
            
            selected_node = st.selectbox("节点", filtered_nodes)
            
            if selected_node:
                node_info = nodes[selected_node]
                st.markdown(f"**类型:** {node_info['type']}")
        
        if st.button("🔗 挂载", use_container_width=True):
            if selected_skill and selected_node:
                if skill_manager.mount_to_node(selected_skill, selected_node):
                    st.success(f"✅ 已将 {selected_skill} 挂载到 {selected_node}")
                    st.rerun()
                else:
                    st.error("❌ 挂载失败")
        
        st.markdown("---")
        st.subheader("📋 挂载状态")
        
        for node_name, node_info in nodes.items():
            mounted_skills = skill_manager.get_mounted_skills(node_name)
            if mounted_skills:
                st.markdown(f"**{node_name}** ({node_info['type']}):")
                for skill in mounted_skills:
                    st.caption(f"  - {skill.name}")


if __name__ == "__main__":
    main()
