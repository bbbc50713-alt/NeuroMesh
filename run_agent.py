"""
快速启动脚本 - 启动单个Agent节点

使用方法:
    python run_agent.py --name Agent-A --port 10000
    python run_agent.py --name Agent-B --port 10001 --bootstrap /ip4/127.0.0.1/tcp/10000/p2p/xxx
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import Agent, AgentConfig


async def main():
    parser = argparse.ArgumentParser(description="Start an Agent node")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--port", type=int, default=0, help="P2P port (0 for random)")
    parser.add_argument("--bootstrap", nargs="*", default=[], help="Bootstrap peer addresses")
    parser.add_argument("--server", default="", help="Central server URL")
    parser.add_argument("--create-todo", help="Create a todo on startup")
    
    args = parser.parse_args()
    
    config = AgentConfig(
        name=args.name,
        port=args.port,
        bootstrap_peers=args.bootstrap,
        server_url=args.server
    )
    
    agent = Agent(config)
    
    try:
        peer_id = await agent.start()
        
        if args.create_todo:
            await asyncio.sleep(2)
            await agent.create_todo(args.create_todo)
        
        print("\nPress Ctrl+C to stop...")
        
        while True:
            await asyncio.sleep(10)
            agent.print_status()
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
