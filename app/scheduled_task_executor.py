from dataclasses import dataclass

from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .ebay_tool import ebay_context_text, search_ebay
from .weather_tool import get_weather, weather_context_text
from .web_search_tool import search_web, source_urls, web_search_context_text


@dataclass(frozen=True)
class ScheduledExecutionResult:
    content: str
    source_urls: tuple[str, ...] = ()
    effective_query: str = ""


class ScheduledTaskExecutor:
    """
    Canonical scheduled-task execution logic shared by the Desktop worker and
    the background scheduler runner.
    """

    def __init__(
        self,
        client,
        *,
        query_generator=None,
        get_weather_fn=get_weather,
        weather_context_text_fn=weather_context_text,
        search_ebay_fn=search_ebay,
        ebay_context_text_fn=ebay_context_text,
        get_computer_status_fn=get_computer_status,
        computer_status_context_text_fn=computer_status_context_text,
        search_web_fn=search_web,
        web_search_context_text_fn=web_search_context_text,
        source_urls_fn=source_urls,
    ):
        self.client = client
        self.query_generator = query_generator or self._generate_search_query
        self.get_weather_fn = get_weather_fn
        self.weather_context_text_fn = weather_context_text_fn
        self.search_ebay_fn = search_ebay_fn
        self.ebay_context_text_fn = ebay_context_text_fn
        self.get_computer_status_fn = get_computer_status_fn
        self.computer_status_context_text_fn = computer_status_context_text_fn
        self.search_web_fn = search_web_fn
        self.web_search_context_text_fn = web_search_context_text_fn
        self.source_urls_fn = source_urls_fn

    def _generate_search_query(self, prompt, model):
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the user's scheduled research task into one concise web "
                    "search query. Preserve product/model/proper names. Prefer English "
                    "search terms when that improves international web results. "
                    "Return ONLY the search query, no explanation, no quotes."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        query = self.client.chat_once(
            model=model,
            messages=messages,
        ).strip()
        query = " ".join(query.splitlines()[0].strip().strip('\"\'').split())
        return query[:180] or prompt[:180]

    def _build_context(self, task, model):
        task_type = str(task.get("task_type", "weather")).strip().lower()
        urls = []
        effective_query = ""

        if task_type == "weather":
            location = str(task.get("location", "")).strip()
            if not location:
                raise RuntimeError("Weather task requires a location.")
            weather = self.get_weather_fn(location)
            return self.weather_context_text_fn(weather), urls, effective_query

        if task_type == "ebay":
            query = str(task.get("ebay_query", "")).strip()
            prompt_query = str(task.get("prompt", "")).strip()
            if not query or query.lower() in {"ebay", "ebay.de"}:
                query = prompt_query
            if not query:
                raise RuntimeError("eBay Search task requires a query or prompt.")
            payload = self.search_ebay_fn(
                query,
                max_results=int(task.get("ebay_max_results", 8) or 8),
            )
            urls = [
                str(item.get("url", "")).strip()
                for item in payload.get("results") or []
                if str(item.get("url", "")).strip()
            ]
            effective_query = query
            return self.ebay_context_text_fn(payload), urls, effective_query

        if task_type == "computer":
            payload = self.get_computer_status_fn()
            return (
                self.computer_status_context_text_fn(payload),
                urls,
                effective_query,
            )

        if task_type == "custom":
            if not bool(task.get("web_search_enabled", False)):
                return "", urls, effective_query

            query = str(task.get("web_query", "")).strip()
            if not query:
                query = self.query_generator(
                    str(task.get("prompt", "")).strip(),
                    model,
                )

            payload = self.search_web_fn(
                query,
                max_results=int(task.get("web_max_results", 6) or 6),
                fetch_pages=bool(task.get("web_fetch_pages", True)),
            )
            urls = list(self.source_urls_fn(payload))
            effective_query = query
            return (
                self.web_search_context_text_fn(payload),
                urls,
                effective_query,
            )

        raise RuntimeError(f"Unsupported scheduled task type: {task_type}")

    def execute(self, task):
        task = dict(task or {})
        prompt = str(task.get("prompt", "")).strip()
        model = str(task.get("model", "")).strip()
        task_type = str(task.get("task_type", "weather")).strip().lower()

        if not prompt:
            raise RuntimeError("Scheduled task prompt is empty.")
        if not model:
            raise RuntimeError("Scheduled task model is not set.")

        tool_context, urls, effective_query = self._build_context(task, model)

        if tool_context:
            user_content = (
                f"SCHEDULED TASK TYPE: {task_type}\n"
                f"SCHEDULED TASK:\n{prompt}\n\n"
                f"AUTHORIZED TOOL DATA:\n{tool_context}"
            )
            system_content = (
                "You are running a scheduled local-assistant task. "
                "For current or external facts, use ONLY the AUTHORIZED TOOL DATA "
                "in the user message. Do not use memory or prior knowledge to fill "
                "missing facts. If the supplied sources are irrelevant or do not "
                "support the requested topic, explicitly say that no relevant "
                "sources were found instead of answering a different topic. "
                "Never invent scores, ratings, prices, specifications, dates, "
                "comparisons, or recommendations. Keep the answer concise unless "
                "the task asks for detail."
            )
        else:
            user_content = (
                "SCHEDULED TASK TYPE: custom\n"
                f"SCHEDULED TASK:\n{prompt}"
            )
            system_content = (
                "You are running a scheduled local-assistant task. "
                "No live external data source is attached to this task. "
                "Do not claim that you checked current internet data."
            )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        content = self.client.chat_once(
            model=model,
            messages=messages,
        )
        if not str(content or "").strip():
            raise RuntimeError("The model returned an empty scheduled result.")

        final_content = str(content).strip()
        if urls:
            source_lines = "\n".join(f"- {url}" for url in urls[:10])
            final_content += (
                "\n\n---\n"
                f"Search query: {effective_query}\n"
                "Sources:\n"
                f"{source_lines}"
            )

        return ScheduledExecutionResult(
            content=final_content,
            source_urls=tuple(urls),
            effective_query=effective_query,
        )
