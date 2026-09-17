import re
from urllib.parse import parse_qs, urlparse


def _kit_total_capacity(exact_kit):
    match = re.fullmatch(
        r"(\d+)x(\d+)(gb|tb)",
        str(exact_kit or "").strip().lower(),
    )
    if not match:
        return ""
    count = int(match.group(1))
    size = int(match.group(2))
    unit = match.group(3).upper()
    return f"{count * size}{unit}"


def _is_memory_kit_plan(plan):
    return bool(
        plan.get("exact_kit")
        and plan.get("memory_type")
        and plan.get("speed_mhz") is not None
    )


def _is_generic_shopping_url(url):
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False

    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower().rstrip("/")
    query = parse_qs(parsed.query)

    if not host:
        return False

    if "ebay." in host:
        if path.startswith("/sch") or "_nkw" in query:
            return True

    if "amazon." in host:
        if path in {"/s", "/gp/search"} or "k" in query:
            return True

    generic_paths = {
        "/search",
        "/suche",
        "/shop/search",
        "/products/search",
    }
    if path in generic_paths:
        return True

    generic_query_keys = {"search", "query", "keyword", "keywords"}
    if generic_query_keys.intersection(query):
        return True

    return False


def install_shopping_search_patch(web_search_tool):
    if getattr(web_search_tool, "_shopping_search_patch_installed", False):
        return

    original_build_provider_query = web_search_tool.build_provider_query
    original_filter_relevant_results = web_search_tool._filter_relevant_results

    def build_provider_query(plan):
        base = original_build_provider_query(plan)
        if not _is_memory_kit_plan(plan):
            return base

        parts = []
        exact_kit = web_search_tool._format_exact_kit(plan.get("exact_kit"))
        if exact_kit:
            parts.append(exact_kit)

        total_capacity = _kit_total_capacity(plan.get("exact_kit"))
        if total_capacity:
            parts.append(total_capacity)

        memory_type = str(plan.get("memory_type") or "").upper()
        if memory_type:
            parts.append(memory_type)

        speed_mhz = plan.get("speed_mhz")
        if speed_mhz is not None:
            parts.append(f"{int(speed_mhz)} MHz")

        ignored_topic_tokens = {
            "mhz",
            "mts",
            "mtps",
            "eur",
            "usd",
            "gb",
            "tb",
            "ram",
        }
        topic_terms = []
        for term in web_search_tool._query_terms(plan.get("query") or ""):
            normalized = web_search_tool._normalized_spec_text(term)
            if normalized in {
                web_search_tool._normalized_spec_text(plan.get("exact_kit")),
                web_search_tool._normalized_spec_text(plan.get("memory_type")),
                str(speed_mhz or ""),
            }:
                continue
            if term.isdigit() or normalized in ignored_topic_tokens:
                continue
            if term not in topic_terms:
                topic_terms.append(term)
            if len(topic_terms) >= 3:
                break

        parts.extend(topic_terms)
        parts.extend(["RAM", "kit", "kaufen"])

        if plan.get("country") == "DE":
            parts.extend(["Germany", "Deutschland"])

        if plan.get("max_price") is not None and plan.get("currency"):
            amount = float(plan["max_price"])
            display = str(int(amount)) if amount.is_integer() else str(amount)
            parts.append(f"under {display} {plan['currency']}")

        canonical = " ".join(
            str(value).strip() for value in parts if str(value).strip()
        )
        return canonical[:260] or base

    def filter_relevant_results(
        query,
        results,
        *,
        plan=None,
        require_verified=True,
    ):
        effective_plan = plan or web_search_tool.build_search_plan(query)
        bounded_results = list(results)
        if _is_memory_kit_plan(effective_plan):
            product_results = [
                item for item in bounded_results
                if not _is_generic_shopping_url(item.get("url", ""))
            ]
            if product_results:
                bounded_results = product_results

        return original_filter_relevant_results(
            query,
            bounded_results,
            plan=effective_plan,
            require_verified=require_verified,
        )

    web_search_tool.build_provider_query = build_provider_query
    web_search_tool._filter_relevant_results = filter_relevant_results
    web_search_tool._shopping_search_patch_installed = True
