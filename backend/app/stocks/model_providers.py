"""OpenAI Chat Completions 兼容适配及自定义公网端点校验。"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx

PROVIDERS = {
    "deepseek": dict(label="DeepSeek", base_url="https://api.deepseek.com", default_model="deepseek-flash", token_field="max_tokens"),
    "qwen": dict(label="通义千问 / 百炼", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", default_model="qwen-plus", token_field="max_tokens"),
    "zhipu": dict(label="智谱 GLM", base_url="https://open.bigmodel.cn/api/paas/v4", default_model="glm-5.3", token_field="max_tokens"),
    "openai": dict(label="OpenAI", base_url="https://api.openai.com/v1", default_model="", token_field="max_completion_tokens"),
    "custom": dict(label="自定义兼容接口", base_url="", default_model="", token_field="max_tokens"),
}


class EndpointError(ValueError):
    pass


def normalize_base(provider, value):
    if provider not in PROVIDERS:
        raise EndpointError("不支持该模型服务商。")
    value = (value or PROVIDERS[provider]["base_url"]).strip().rstrip("/")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise EndpointError("API 地址格式不正确。") from None
    if (parts.scheme != "https" or not host or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or not re.fullmatch(r"[a-z0-9.-]+", host)
            or host.endswith(".") or ".." in host or host == "localhost" or "." not in host
            or host.endswith((".localhost", ".local", ".internal"))):
        raise EndpointError("API 地址须为公网 HTTPS Base URL，不能带账号、密码、查询参数或锚点。")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise EndpointError("不能使用本机或内网 API 地址。")
    path = parts.path.rstrip("/")
    if path.endswith(("/chat/completions", "/models", "/responses")):
        raise EndpointError("请填写 Base URL，不要包含 /chat/completions、/models 或 /responses。")
    normalized = urlunsplit(("https", host + (":%d" % port if port and port != 443 else ""), path, "", ""))
    if provider != "custom":
        expected = PROVIDERS[provider]["base_url"]
        qwen_host = host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"} or host.endswith(".maas.aliyuncs.com")
        if normalized != expected and not (provider == "qwen" and qwen_host and path == "/compatible-mode/v1" and port in (None, 443)):
            raise EndpointError("该预设须使用对应官方地址；其他地址请选择自定义兼容接口。")
    return normalized


def request(credentials, method, suffix, *, body=None, transport=None, timeout=45):
    base = normalize_base(credentials.provider, credentials.base_url)
    url = base + suffix
    headers = {"Authorization": "Bearer " + credentials.key.get_secret_value()}
    extensions = {}
    if credentials.provider == "custom":
        # 校验所有解析结果并固定本次连接IP，避免DNS二次解析或重定向访问内网。
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port or 443
        try:
            addresses = {row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        except OSError:
            raise EndpointError("自定义 API 域名解析失败。") from None
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise EndpointError("自定义 API 地址必须仅解析到公网地址。")
        address = sorted(addresses)[0]
        authority = ("[" + address + "]") if ":" in address else address
        url = urlunsplit(("https", authority + (":%d" % port if port != 443 else ""), parts.path, "", ""))
        headers["Host"] = host + (":%d" % port if port != 443 else "")
        extensions["sni_hostname"] = host
    # 不跟随重定向；自定义端点直连已核实IP，保留原域名做TLS证书验证。
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False,
                      trust_env=credentials.provider != "custom") as client:
        response = client.request(method, url, json=body, headers=headers, extensions=extensions)
        response.raise_for_status()
        return response


def configure_body(body, credentials):
    body[credentials.token_field] = 4096
    if credentials.json_mode == "json_object":
        body["response_format"] = {"type": "json_object"}
    if credentials.provider == "deepseek":
        body["thinking"] = {"type": "disabled"}
    elif credentials.provider == "qwen" and credentials.model.lower().startswith("qwen"):
        body["enable_thinking"] = False
    return body
