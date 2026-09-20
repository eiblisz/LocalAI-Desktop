from dataclasses import dataclass

from .crypto_market_data import is_crypto_quote_request
from .multi_asset_market_data import is_multi_asset_quote_request
from .web_intent import (
    ACTION_MEMORY_WRITE,
    ACTION_WEB_RESEARCH,
    ActionPlan,
    plan_user_action,
)


ROUTE_MEMORY_WRITE = "memory_write"
ROUTE_CRYPTO_MARKET = "crypto_market"
ROUTE_MULTI_ASSET_MARKET = "multi_asset_market"
ROUTE_MARKET_WEB = "market_web"
ROUTE_WEB = "web"
ROUTE_CHAT = "chat"


@dataclass(frozen=True)
class ActionDecision:
    plan: ActionPlan
    route: str
    use_web: bool
    market_fallback: bool = False


class ActionRuntime:
    """
    Host-side action routing for one user request.

    The runtime does not create Qt workers or threads. It only converts the
    existing intent plan plus host capability availability into an explicit
    execution route.
    """

    def decide(
        self,
        user_text,
        *,
        model_text=None,
        force_web=False,
        crypto_market_available=False,
        multi_asset_market_available=False,
    ):
        user_text = str(user_text or "")
        execution_text = (
            str(model_text)
            if model_text is not None
            else user_text
        )

        plan = plan_user_action(
            user_text,
            force_web=bool(force_web),
        )

        if plan.has(ACTION_MEMORY_WRITE):
            return ActionDecision(
                plan=plan,
                route=ROUTE_MEMORY_WRITE,
                use_web=False,
            )

        use_web = plan.has(ACTION_WEB_RESEARCH)
        if not use_web:
            return ActionDecision(
                plan=plan,
                route=ROUTE_CHAT,
                use_web=False,
            )

        if is_crypto_quote_request(execution_text):
            if crypto_market_available:
                return ActionDecision(
                    plan=plan,
                    route=ROUTE_CRYPTO_MARKET,
                    use_web=True,
                )
            return ActionDecision(
                plan=plan,
                route=ROUTE_MARKET_WEB,
                use_web=True,
                market_fallback=True,
            )

        if is_multi_asset_quote_request(execution_text):
            if multi_asset_market_available:
                return ActionDecision(
                    plan=plan,
                    route=ROUTE_MULTI_ASSET_MARKET,
                    use_web=True,
                )
            return ActionDecision(
                plan=plan,
                route=ROUTE_MARKET_WEB,
                use_web=True,
                market_fallback=True,
            )

        return ActionDecision(
            plan=plan,
            route=ROUTE_WEB,
            use_web=True,
        )
