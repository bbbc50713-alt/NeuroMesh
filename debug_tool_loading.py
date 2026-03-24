"""
调试脚本 - 检查工具加载问题
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.skill_loader import SkillLoader, SkillLoadState


async def debug_tool_loading():
    """调试工具加载"""
    loader = SkillLoader()
    
    # 创建测试 skill 目录
    test_dir = tempfile.mkdtemp(prefix="debug_skill_")
    
    skill_md = os.path.join(test_dir, "skill.md")
    with open(skill_md, "w", encoding="utf-8") as f:
        f.write("# Debug Skill\n\nA debug skill")
    
    script_dir = os.path.join(test_dir, "script")
    os.makedirs(script_dir, exist_ok=True)
    script_file = os.path.join(script_dir, "tools.py")
    with open(script_file, "w", encoding="utf-8") as f:
        f.write('''
def tool_one(args):
    """工具一"""
    return {"result": "tool_one executed"}

def tool_two(args):
    """工具二"""
    return {"result": "tool_two executed"}
''')
    
    # 注册 skill
    skill_name = os.path.basename(test_dir)
    print(f"Skill 目录: {test_dir}")
    print(f"Skill 名称: {skill_name}")
    
    metadata = loader.register_skill(test_dir)
    print(f"注册结果: {metadata}")
    print(f"元数据中的 skills: {list(loader.skills_metadata.keys())}")
    
    # 加载 skill
    tools = await loader.load_skill_full(skill_name)
    print(f"加载的工具数量: {len(tools)}")
    
    for tool in tools:
        print(f"  工具: {tool.name}")
    
    # 尝试确保工具加载
    tool_name = f"skill_{skill_name}_tool_one"
    print(f"尝试加载工具: {tool_name}")
    tool = await loader.ensure_tool_loaded(tool_name)
    print(f"加载结果: {tool}")
    
    # 清理
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(debug_tool_loading())
