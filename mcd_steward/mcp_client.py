"""麦当劳 MCP Server (Streamable HTTP) 的极简 JSON-RPC 2.0 客户端。

只依赖标准库，任何人 clone 下来就能跑。

接入方式（见 README）
---------------------
    {
      "mcpServers": {
        "mcd-mcp": {
          "type": "streamablehttp",
          "url": "https://mcp.mcd.cn",
          "headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
        }
      }
    }

本模块只负责"把 Tool 调出来"，不含任何业务逻辑，
方便你用 curl 或别的语言重写时对照参考。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-points-steward", "version": "1.0.0"}


class McpError(RuntimeError):
    """MCP 调用失败。"""


class McpClient:
    """Streamable HTTP 传输下的 MCP 客户端。"""

    def __init__(self, url: str = "https://mcp.mcd.cn", token: str = "", timeout: float = 30.0) -> None:
        if not token:
            raise McpError("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN")
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._id = 0
        self._initialized = False
        self._tool_names: List[str] = []

    # ---------------------------------------------------------------- HTTP #

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "mcd-points-steward/1.0.0",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: Dict[str, Any], expect_response: bool = True) -> Optional[Dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                if not expect_response:
                    return None
                raw = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("Content-Type", "")
                if "text/event-stream" in ctype:
                    return _parse_sse(raw)
                if not raw.strip():
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:  # pragma: no cover - 网络分支
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code == 401:
                raise McpError("MCP Token 无效或已过期（401），请到 https://open.mcd.cn/mcp 重新申请") from exc
            if exc.code == 429:
                raise McpError("触发限流（429），单 Token 每分钟最多 600 次请求，请降低频率") from exc
            raise McpError(f"MCP HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - 网络分支
            raise McpError(f"网络错误，无法连接 {self.url}：{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise McpError(f"响应不是合法 JSON：{raw[:200]}") from exc

    # ------------------------------------------------------------ protocol #

    def initialize(self) -> None:
        """完成 initialize + notifications/initialized 握手。"""
        if self._initialized:
            return
        self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        })
        # 通知类消息不需要响应体
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)
        self._initialized = True

    def list_tools(self) -> List[str]:
        """返回服务端当前开放的全部 Tool 名称。"""
        self.initialize()
        resp = self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}})
        tools = (resp or {}).get("result", {}).get("tools", [])
        self._tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
        return self._tool_names

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """调用一个 Tool，返回解析后的业务数据（尽量还原成 dict/list）。"""
        self.initialize()
        resp = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        if resp is None:
            raise McpError(f"Tool {name} 无响应")
        if "error" in resp:
            err = resp["error"]
            raise McpError(f"Tool {name} 调用失败：{err.get('message', err)}")
        result = resp.get("result", {})
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)]
            raise McpError(f"Tool {name} 返回错误：{' '.join(texts)[:300]}")
        return _extract_payload(result)


def _parse_sse(raw: str) -> Dict[str, Any]:
    """从 SSE 响应体中取出最后一条 JSON-RPC 消息。"""
    message: Optional[Dict[str, Any]] = None
    data_lines: List[str] = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line.startswith("event:") and message is None and not data_lines:
            continue
        elif not line.strip() and data_lines:
            chunk = "\n".join(data_lines)
            data_lines = []
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("method") != "notifications/progress":
                message = parsed
    if message is None and data_lines:
        try:
            message = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            message = None
    return message or {}


def _extract_payload(result: Dict[str, Any]) -> Any:
    """从 tools/call 的 result 中提取业务负载。

    优先取 ``structuredContent``；否则把 ``content`` 中的 text 尝试解析为 JSON；
    都不是就返回纯文本列表。
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("result", "data", "content"):
            if key in structured and isinstance(structured[key], (dict, list)):
                return structured[key]
        return structured

    contents = result.get("content")
    if isinstance(contents, list) and contents:
        texts: List[str] = []
        for c in contents:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(str(c.get("text", "")))
        blob = "\n".join(texts).strip()
        if not blob:
            return []
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            pass
        # 有些服务返回被包了一层的 JSON 字符串
        try:
            inner = json.loads(blob)
            if isinstance(inner, str):
                return json.loads(inner)
            return inner
        except (json.JSONDecodeError, ValueError):
            return blob
    return result
