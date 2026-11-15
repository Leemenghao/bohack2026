"""Connection metadata on disk; endpoint-bound secrets in the macOS Keychain."""
import copy
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from dotenv import dotenv_values

from research_agent.research.ledger import PRICING
from research_agent.paths import DATA_ROOT

ROOT = DATA_ROOT
SETTINGS_PATH = Path.home() / "Library/Application Support/LuLu Research/settings.json"
DEFAULTS = {
    "model": {"base_url": "https://api.deepseek.com", "name": "deepseek-flash", "prices": None},
    "search": {"base_url": "https://api.deepseek.com/v1/tools"},
}
lock = RLock()


def keychain():
    if sys.platform != "darwin":
        raise ValueError("当前密钥保存仅支持 macOS 钥匙串；其他平台可使用环境变量。")
    from keyring.backends.macOS import Keyring
    return Keyring()


def account(kind, url):
    return kind + ":" + hashlib.sha256(url.encode()).hexdigest()


def load_settings():
    with lock:
        if not SETTINGS_PATH.exists():
            return copy.deepcopy(DEFAULTS)
        return json.loads(SETTINGS_PATH.read_text())


def environment_key(url):
    host = urlsplit(url).hostname
    # Never forward an existing credential to an arbitrary replacement endpoint.
    name = {"api.deepseek.com": "DEEPSEEK_API_KEY", "aiping.cn": "AIPING_API_KEY"}.get(host)
    if not name:
        return "", None
    values = dotenv_values(ROOT / ".env")
    return (os.environ.get(name) or values.get(name) or "").strip(), name


def credential(kind, url):
    secret = keychain().get_password("LuLu Research", account(kind, url)) if sys.platform == "darwin" else None
    if secret:
        return secret, "keychain"
    secret, name = environment_key(url)
    return secret, f"env:{name}" if secret else "missing"


def public_settings():
    config = load_settings()
    for kind in ("model", "search"):
        secret, source = credential(kind, config[kind]["base_url"])
        config[kind].update(key_configured=bool(secret), key_source=source)
    return config


def validate_url(value):
    if not isinstance(value, str) or len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError("请输入有效的 API Base URL。")
    url = urlsplit(value)
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if (not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment
            or not (url.scheme == "https" or (local and url.scheme == "http"))):
        raise ValueError("API 地址须使用 HTTPS（本机可用 HTTP），且不能包含密钥、查询参数或账号密码。")
    return value.rstrip("/")


def save_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("设置格式不正确。")
    config, secrets = {}, {}
    for kind in ("model", "search"):
        section = payload.get(kind)
        if not isinstance(section, dict):
            raise ValueError("请填写模型与搜索连接。")
        config[kind] = {"base_url": validate_url(section.get("base_url"))}
        secret = section.get("api_key", "")
        if not isinstance(secret, str) or len(secret) > 4096 or any(c.isspace() for c in secret):
            raise ValueError("API Key 格式不正确。")
        secrets[kind] = secret
    name = payload["model"].get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 150:
        raise ValueError("请填写服务商提供的完整模型 ID。")
    config["model"]["name"] = name.strip()
    prices = payload["model"].get("prices")
    if prices is not None:
        if (not isinstance(prices, dict) or set(prices) != {"input", "output", "cache_read"}
                or any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in prices.values())):
            raise ValueError("自定义单价需完整填写输入、输出、缓存命中价格（元 / 百万 token）。")
    config["model"]["prices"] = prices
    with lock:
        vault = keychain()
        # Validate everything before writing credentials. Blank means retain the credential for this exact endpoint.
        for kind, section in config.items():
            secret = secrets[kind]
            if not secret and not vault.get_password("LuLu Research", account(kind, section["base_url"])):
                secret, _ = environment_key(section["base_url"])
            if secret:
                vault.set_password("LuLu Research", account(kind, section["base_url"]), secret)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = SETTINGS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        temporary.chmod(0o600)
        temporary.replace(SETTINGS_PATH)
        return public_settings()


def runtime_settings():
    with lock:
        config = load_settings()
        for kind in ("model", "search"):
            config[kind]["api_key"] = credential(kind, config[kind]["base_url"])[0]
        return config


def pricing_for(config):
    pricing = copy.deepcopy(PRICING)
    model = config["model"]
    if model.get("prices") is not None:
        pricing["models_per_million"] = {model["name"]: model["prices"]}
        pricing["basis"] = "模型费用按用户配置单价估算，不代表实际扣款"
    elif urlsplit(model["base_url"]).hostname != "api.deepseek.com":
        pricing["models_per_million"] = {}
        pricing["basis"] = "第三方模型单价未配置，模型费用未计量"
    if config["search"]["base_url"] != DEFAULTS["search"]["base_url"]:
        pricing.update(search_per_request=None, fetch_per_request=None)
    pricing["model_endpoint"] = model["base_url"]
    pricing["search_endpoint"] = config["search"]["base_url"]
    return pricing
