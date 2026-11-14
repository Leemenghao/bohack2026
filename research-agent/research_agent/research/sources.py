import re
from hashlib import sha256
from urllib.parse import quote, urlsplit


DATACITE = "https://api.datacite.org/dois"
TAVILY = "https://api.tavily.com"
MAX_CONTENT_CHARS = 60_000
MAX_EVIDENCE_CHARS = 3_000


# Excerpts are Chinese summaries of the linked primary sources.
SOURCES = (
    (
        "mlx-cache",
        "MLX-LM 0.32.2 · 前缀缓存匹配",
        "https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/models/cache.py#L1652-L1672",
        "缓存可匹配完整输入或已见过的 token 前缀。在允许裁剪时，MLX-LM 可以从较长的缓存条目保留共同前缀，并把未匹配的后缀交给模型继续处理。",
        ("mlx", "prefix", "前缀", "复用", "命中", "cache", "缓存", "kv", "prefill"),
    ),
    (
        "mlx-usage",
        "MLX-LM 0.32.2 · 流式响应中的缓存用量",
        "https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/server.py#L1720-L1743",
        "服务端在流式用量响应中返回 prompt_tokens 和 completion_tokens，并在可用时通过 prompt_tokens_details.cached_tokens 报告缓存命中的 token 数。",
        ("mlx", "cached_tokens", "usage", "命中", "token", "指标", "缓存", "ttft"),
    ),
    (
        "vllm-apc",
        "vLLM · Automatic Prefix Caching",
        "https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/",
        "已有请求的 KV 缓存可服务共享前缀的请求，省去对应的预填充计算。该机制节省的是处理输入的时间，生成新 token 的计算仍需执行。",
        ("vllm", "prefix", "前缀", "prefill", "预填充", "延迟", "ttft", "decode"),
    ),
    (
        "sglang-radix",
        "SGLang: Efficient Execution of Structured Language Model Programs",
        "https://arxiv.org/abs/2312.07104v2",
        "论文提出 RadixAttention 来复用 KV 缓存，以加速需要多次生成调用的语言模型程序。可作为前缀复用的研究背景，论文的性能结果来自 SGLang 的实验条件。",
        ("sglang", "radixattention", "论文", "kv", "prefix", "前缀", "复用"),
    ),
    (
        "sklearn-class-weight",
        "scikit-learn 1.7 · LogisticRegression",
        "https://scikit-learn.org/1.7/modules/generated/sklearn.linear_model.LogisticRegression.html",
        "class_weight='balanced' 按训练集类别频次的倒数调整权重。比较加权前后时，应同时观察少数类的召回率和精确率。",
        ("classification", "imbalance", "class_weight", "logistic", "不平衡", "分类", "类别加权", "逻辑回归"),
    ),
)


def find_sources(query):
    """Rank the local collection by matched terms, retaining up to three hits."""
    query = query.strip().casefold()
    hits = []
    for source_id, title, url, excerpt, keywords in SOURCES:
        score = sum(
            bool(re.search(rf"\b{re.escape(keyword)}\b", query))
            if keyword.isascii()
            else keyword in query
            for keyword in keywords
        )
        if score:
            hits.append((score, {"source_id": source_id, "title": title, "url": url, "excerpt": excerpt}))
    hits.sort(key=lambda hit: hit[0], reverse=True)
    return [source for _, source in hits[:3]]


def _tavily_request(endpoint, key, payload):
    # Imported lazily so the local collection works without network deps installed.
    import httpx

    response = httpx.post(
        f"{TAVILY}/{endpoint}",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["results"]


def _datacite_get(url, params=None):
    import httpx

    response = httpx.get(url, params=params, timeout=8)
    response.raise_for_status()
    return response.json()["data"]


def search_web(query, tavily_key=""):
    """Search general web with Tavily, or arXiv metadata with the public DataCite API."""
    sources = []
    if tavily_key:
        hits = _tavily_request("search", tavily_key, {
            "query": query, "search_depth": "basic", "max_results": 3,
            "auto_parameters": False, "include_raw_content": False,
        })
        for hit in hits:
            url = hit["url"]
            link = urlsplit(url)
            if link.scheme not in ("http", "https") or not link.hostname or link.username is not None:
                continue
            source_id = "web-" + sha256(url.encode()).hexdigest()[:12]
            sources.append({"source_id": source_id, "title": hit["title"], "url": url,
                            "excerpt": hit["content"][:500], "provider": "tavily"})
    else:
        hits = _datacite_get(DATACITE, {
            "query": f"prefix:10.48550 AND ({query})", "page[size]": 3, "sort": "relevance",
        })
        for hit in hits:
            paper = hit["attributes"]
            doi = paper["doi"].lower()
            if not re.fullmatch(r"10\.48550/arxiv\.\d{4}\.\d{4,5}(v\d+)?", doi):
                continue
            arxiv_id = doi.split("arxiv.", 1)[1]
            sources.append({"source_id": f"arxiv-{arxiv_id}", "title": paper["titles"][0]["title"],
                            "url": f"https://arxiv.org/abs/{arxiv_id}", "doi": doi,
                            "excerpt": "", "provider": "datacite"})
    return sources


def fetch_web_source(source, tavily_key=""):
    """Read a previously discovered source. Return the content and its actual scope."""
    if source["provider"] == "tavily":
        results = _tavily_request("extract", tavily_key, {
            "urls": [source["url"]], "extract_depth": "basic", "format": "markdown", "timeout": 8,
        })
        content = results[0]["raw_content"] if results else ""
        return "webpage_text", (content or "").strip()

    paper = _datacite_get(f"{DATACITE}/{quote(source['doi'], safe='/')}")["attributes"]
    abstract = next((item["description"] for item in paper["descriptions"]
                     if item["descriptionType"] == "Abstract"), "")
    return "paper_abstract", abstract.strip()
