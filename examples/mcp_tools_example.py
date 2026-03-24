"""
MCP工具定义示例

这个文件定义了可以被加载到P2P网络的MCP工具。
"""

TOOLS = [
    {
        "name": "mcp/weather_query",
        "description": "查询指定城市的天气信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如：北京、上海"
                },
                "days": {
                    "type": "integer",
                    "description": "预报天数，默认1天",
                    "default": 1
                }
            },
            "required": ["city"]
        },
        "handler": "query_weather",
        "tags": ["weather", "query", "api"]
    },
    {
        "name": "mcp/database_query",
        "description": "执行SQL查询（只读）",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SELECT语句"
                },
                "database": {
                    "type": "string",
                    "description": "数据库名称",
                    "default": "default"
                }
            },
            "required": ["sql"]
        },
        "handler": "database_query",
        "tags": ["database", "sql", "query"]
    },
    {
        "name": "mcp/camera_capture",
        "description": "从摄像头捕获图像",
        "input_schema": {
            "type": "object",
            "properties": {
                "resolution": {
                    "type": "string",
                    "description": "分辨率，如：1080p, 720p",
                    "default": "1080p"
                },
                "format": {
                    "type": "string",
                    "description": "图像格式",
                    "enum": ["jpg", "png"],
                    "default": "jpg"
                }
            }
        },
        "handler": "camera_capture",
        "tags": ["camera", "image", "hardware"]
    },
    {
        "name": "mcp/file_read",
        "description": "读取文件内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "encoding": {
                    "type": "string",
                    "description": "文件编码",
                    "default": "utf-8"
                }
            },
            "required": ["path"]
        },
        "handler": "file_read",
        "tags": ["file", "io", "read"]
    },
    {
        "name": "mcp/http_request",
        "description": "发送HTTP请求",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "请求URL"
                },
                "method": {
                    "type": "string",
                    "description": "HTTP方法",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "default": "GET"
                },
                "headers": {
                    "type": "object",
                    "description": "请求头"
                },
                "body": {
                    "type": "object",
                    "description": "请求体"
                }
            },
            "required": ["url"]
        },
        "handler": "http_request",
        "tags": ["http", "network", "api"]
    }
]


async def query_weather(args):
    """查询天气"""
    city = args.get("city", "未知")
    days = args.get("days", 1)
    
    return {
        "city": city,
        "forecast": [
            {
                "day": i + 1,
                "weather": "晴" if i % 2 == 0 else "多云",
                "temp_high": 25 + i,
                "temp_low": 15 + i
            }
            for i in range(days)
        ],
        "humidity": 65,
        "wind": "东南风3级"
    }


async def database_query(args):
    """数据库查询"""
    sql = args.get("sql", "")
    database = args.get("database", "default")
    
    if not sql.upper().startswith("SELECT"):
        return {"error": "只允许SELECT查询"}
    
    return {
        "database": database,
        "sql": sql,
        "rows": [
            {"id": 1, "name": "示例数据1"},
            {"id": 2, "name": "示例数据2"}
        ],
        "row_count": 2
    }


async def camera_capture(args):
    """摄像头捕获"""
    resolution = args.get("resolution", "1080p")
    format = args.get("format", "jpg")
    
    return {
        "status": "success",
        "resolution": resolution,
        "format": format,
        "image_data": "base64_encoded_image_data_here...",
        "timestamp": "2024-01-15T10:30:00Z",
        "size_bytes": 102400
    }


async def file_read(args):
    """读取文件"""
    path = args.get("path")
    encoding = args.get("encoding", "utf-8")
    
    if not path:
        return {"error": "路径不能为空"}
    
    return {
        "path": path,
        "content": f"文件内容示例...",
        "encoding": encoding,
        "size": 1024
    }


async def http_request(args):
    """HTTP请求"""
    url = args.get("url")
    method = args.get("method", "GET")
    headers = args.get("headers", {})
    body = args.get("body")
    
    return {
        "url": url,
        "method": method,
        "status_code": 200,
        "response": {"message": "请求成功"},
        "headers": {"content-type": "application/json"}
    }
