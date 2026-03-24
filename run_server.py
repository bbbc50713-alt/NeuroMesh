"""
启动中心服务器

使用方法:
    python run_server.py --port 8000
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import run_server


def main():
    parser = argparse.ArgumentParser(description="Start Central Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--db", default="agent_todos.db", help="Database path")
    
    args = parser.parse_args()
    run_server(args.host, args.port, args.db)


if __name__ == "__main__":
    main()
