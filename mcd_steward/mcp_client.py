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

工程要点
--------
1. **持久化连接**：用 ``http.client.HTTPSConnection`` 保持 keep-alive，
   避免每个请求都重建 TLS 握手。这在企业代理 / WAF 环境下是必需的 ——
   高频新建连接会被中间设备掐断（表现为 ``SSLEOFError``）。
2. **支持 HTTP 代理**：自动读取 ``https_proxy`` / ``HTTPS_PROXY`` 环境变量，
   用 CONNECT 隧道连接。国内公司网络几乎都要走这一步。
3. **自动重连重试**：连接被复用端关闭时自动重建并重放请求。
4. **双响应格式**：同时兼容 ``application/json`` 与 ``text/event-stream``。
"""

from __future__ import annotations

import http.client
import json
import os
import ssl
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-points-steward", "version": "1.0.0"}

_RETRYABLE = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    http.client.IncompleteRead,
    ConnectionResetError,
    ConnectionAbortedError,
    ssl.SSLEOFError,
    ssl.SSLError,
    OSError,
)


class McpError(RuntimeError):
    """MCP 调用失败。"""


# --------------------------------------------------------------------------- #
# 传输层
# --------------------------------------------------------------------------- #

def _proxy_from_env() -> Optional[Tuple[str, int, Dict[str, str]]]:
    """从环境变量读取 HTTPS 代理，返回 (host, port, 额外头)。"""
    raw = (os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
           or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or "")
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urllib.parse.urlparse(raw)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    headers: Dict[str, str] = {}
    if parsed.username:
        token = parsed.username
        if parsed.password:
            token += ":" + parsed.password
        import base64
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(
            token.encode()).decode()
    return host, port, headers


class _Transport:
    """带 keep-alive、代理支持与自动重连的 HTTP 传输。"""

    def __init__(self, url: str, timeout: float = 30.0, max_retries: int = 3) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise McpError(f"仅支持 https 端点，收到：{url}")
        self.host = parsed.hostname or ""
        self.port = parsed.port or 443
        self.path = parsed.path or "/"
        self.timeout = timeout
        self.max_retries = max_retries
        self._conn: Optional[http.client.HTTPSConnection] = None
        self._proxy = _proxy_from_env()

    # ------------------------------------------------------------ 连接管理 #

    def _new_conn(self) -> http.client.HTTPSConnection:
        ctx = ssl.create_default_context()
        if self._proxy:
            p_host, p_port, p_headers = self._proxy
            conn = http.client.HTTPSConnection(p_host, p_port, timeout=self.timeout, context=ctx)
            tunnel_headers = {"Proxy-Connection": "Keep-Alive"}
            tunnel_headers.update(p_headers)
            conn.set_tunnel(self.host, self.port, headers=tunnel_headers)
        else:
            conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        return conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    # ---------------------------------------------------------------- 请求 #

    def post(self, body: bytes, headers: Dict[str, str]) -> Tuple[int, Dict[str, str], bytes]:
        """POST 一段 JSON，返回 (status, headers, raw_body)。失败时自动重连重试。"""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            if self._conn is None:
                self._conn = self._new_conn()
            try:
                self._conn.request("POST", self.path, body=body, headers=headers)
                resp = self._conn.getresponse()
                raw = resp.read()
                hdrs = {k.lower(): v for k, v in resp.getheaders()}
                # 服务端关闭了复用连接：丢弃，下一次重建
                if hdrs.get("connection", "").lower() == "close":
                    self._close()
                return resp.status, hdrs, raw
            except _RETRYABLE as exc:
                last_exc = exc
                self._close()
                if attempt < self.max_retries - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                break
        assert last_exc is not None
        raise last_exc


# --------------------------------------------------------------------------- #
# MCP 客户端
# --------------------------------------------------------------------------- #

class McpClient:
    """Streamable HTTP 传输下的 MCP 客户端。"""

    def __init__(self, url: str = "https://mcp.mcd.cn", token: str = "",
                 timeout: float = 30.0) -> None:
        if not token:
            raise McpError("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN")
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._id = 0
        self._initialized = False
        self._tool_names: List[str] = []
        self._transport = _Transport(url, timeout=timeout)

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
        try:
            status, hdrs, raw = self._transport.post(body, self._headers())
        except OSError as exc:
            raise McpError(f"网络错误，无法连接 {self.url}：{exc}") from exc

        sid = hdrs.get("mcp-session-id")
        if sid:
            self.session_id = sid

        if status == 401:
            raise McpError("MCP Token 无效或已过期（401），请到 https://open.mcd.cn/mcp 重新申请")
        if status == 429:
            raise McpError("触发限流（429），单 Token 每分钟最多 600 次请求，请降低频率")
        if status >= 400:
            raise McpError(f"MCP HTTP {status}: {raw.decode('utf-8', 'replace')[:300]}")

        if not expect_response:
            return None
        text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            return None
        ctype = hdrs.get("content-type", "")
        if "text/event-stream" in ctype:
            return _parse_sse(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpError(f"响应不是合法 JSON：{text[:200]}") from exc

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
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)
        self._initialized = True

    def list_tools(self) -> List[str]:
        """返回服务端当前开放的全部 Tool 名称。"""
        return [t.get("name", "") for t in self.tool_schemas() if isinstance(t, dict)]

    def tool_schemas(self) -> List[Dict[str, Any]]:
        """返回服务端开放的全部 Tool 的完整定义（含 inputSchema）。"""
        self.initialize()
        resp = self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}})
        tools = (resp or {}).get("result", {}).get("tools", [])
        self._tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
        return tools

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

    def close(self) -> None:
        self._transport._close()


# --------------------------------------------------------------------------- #
# 响应解析
# --------------------------------------------------------------------------- #

def _parse_sse(raw: str) -> Dict[str, Any]:
    """从 SSE 响应体中取出最后一条 JSON-RPC 消息。"""
    message: Optional[Dict[str, Any]] = None
    data_lines: List[str] = []

    def flush() -> None:
        nonlocal message, data_lines
        if not data_lines:
            return
        chunk = "\n".join(data_lines)
        data_lines = []
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict) and parsed.get("method") != "notifications/progress":
            message = parsed

    for line in raw.splitlines():
        line = line.rstrip("\r")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip():
            flush()
    flush()
    return message or {}


def _extract_payload(result: Dict[str, Any]) -> Any:
    """从 tools/call 的 result 中提取业务负载。

    优先取 ``structuredContent``；否则把 ``content`` 中的 text 尝试解析为 JSON；
    都不是就返回纯文本。
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("result", "data", "content"):
            if key in structured and isinstance(structured[key], (dict, list)):
                return structured[key]
        return structured

    contents = result.get("content")
    if isinstance(contents, list) and contents:
        texts = [str(c.get("text", "")) for c in contents
                 if isinstance(c, dict) and c.get("type") == "text"]
        blob = "\n".join(texts).strip()
        if not blob:
            return []
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            pass
        try:
            inner = json.loads(blob)
            if isinstance(inner, str):
                return json.loads(inner)
            return inner
        except (json.JSONDecodeError, ValueError):
            return blob
    return result
