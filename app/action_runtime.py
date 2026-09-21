from dataclasses import dataclass

from .crypto_market_data import is_crypto_quote_request
from .multi_asset_market_data import is_multi_asset_quote_request
from .task_constraints import build_task_constraints
from .web_intent import (
    ACTION_ARTIFACT,
    ACTION_MEMORY_WRITE,
    ACTION_WEB_RESEARCH,
    ActionPlan,
    plan_user_action,
    plan_user_actions,
)


ROUTE_MEMORY_WRITE = "memory_write"
ROUTE_CRYPTO_MARKET = "crypto_market"
ROUTE_MULTI_ASSET_MARKET = "multi_asset_market"
ROUTE_MARKET_WEB = "market_web"
ROUTE_WEB = "web"
ROUTE_ARTIFACT = "artifact"
ROUTE_CHAT = "chat"

AUTH_LOCAL_MODEL = "local_model"
AUTH_MEMORY_WRITE = "memory_write"
AUTH_EXTERNAL_READ = "external_read"
AUTH_ARTIFACT_CREATE = "artifact_create"

DEFAULT_HOST_AUTHORITIES = frozenset({
    AUTH_LOCAL_MODEL,
    AUTH_MEMORY_WRITE,
    AUTH_EXTERNAL_READ,
    AUTH_ARTIFACT_CREATE,
})


@dataclass(frozen=True)
class ActionDecision:
    plan: ActionPlan
    route: str
    use_web: bool
    market_fallback: bool = False


@dataclass(frozen=True)
class ActionContract:
    index: int
    prompt: str
    plan: ActionPlan
    route: str
    use_web: bool
    market_fallback: bool
    required_authorities: tuple[str, ...]
    constraints: object

    @property
    def artifact_plans(self):
        return self.plan.artifact_plans


@dataclass(frozen=True)
class ActionAuthorization:
    allowed: bool
    missing_authorities: tuple[str, ...] = ()


class ActionRuntime:
    """
    Host-side planning and routing for user requests.

    V2 converts one user message into one or more typed ActionContract values.
    The host validates each contract against an explicit authority set before
    execution. This class does not create workers, threads, or side effects.
    """

    @staticmethod
    def _required_authorities(route, *, use_web=False):
        required = []

        if route == ROUTE_MEMORY_WRITE:
            required.append(AUTH_MEMORY_WRITE)
        elif route == ROUTE_ARTIFACT:
            required.extend((AUTH_LOCAL_MODEL, AUTH_ARTIFACT_CREATE))
            if use_web:
                required.append(AUTH_EXTERNAL_READ)
        elif route in {
            ROUTE_CRYPTO_MARKET,
            ROUTE_MULTI_ASSET_MARKET,
            ROUTE_MARKET_WEB,
            ROUTE_WEB,
        }:
            required.append(AUTH_EXTERNAL_READ)
        elif route == ROUTE_CHAT:
            required.append(AUTH_LOCAL_MODEL)

        return tuple(dict.fromkeys(required))

    def _decision_from_plan(
        self,
        plan,
        *,
        execution_text,
        crypto_market_available=False,
        multi_asset_market_available=False,
    ):
        if plan.has(ACTION_MEMORY_WRITE):
            return ActionDecision(
                plan=plan,
                route=ROUTE_MEMORY_WRITE,
                use_web=False,
            )

        use_web = plan.has(ACTION_WEB_RESEARCH)

        if plan.has(ACTION_ARTIFACT):
            return ActionDecision(
                plan=plan,
                route=ROUTE_ARTIFACT,
                use_web=use_web,
            )

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

    def decide(
        self,
        user_text,
        *,
        model_text=None,
        force_web=False,
        disable_web=False,
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
            disable_web=bool(disable_web),
        )
        return self._decision_from_plan(
            plan,
            execution_text=execution_text,
            crypto_market_available=crypto_market_available,
            multi_asset_market_available=multi_asset_market_available,
        )

    def plan_many(
        self,
        user_text,
        *,
        model_context_suffix="",
        force_web=False,
        disable_web=False,
        crypto_market_available=False,
        multi_asset_market_available=False,
    ):
        """
        Plan every explicit action unit independently and preserve source order.

        Attachments or other host-provided model context may be supplied as one
        suffix. It is considered for routing each unit but does not alter the
        stored user prompt or the user-visible action contract.
        """
        planned = plan_user_actions(
            user_text,
            force_web=bool(force_web),
            disable_web=bool(disable_web),
        )
        suffix = str(model_context_suffix or "")
        constraints = build_task_constraints(user_text)

        contracts = []
        for index, item in enumerate(planned):
            execution_text = str(item.prompt or "") + suffix
            decision = self._decision_from_plan(
                item.plan,
                execution_text=execution_text,
                crypto_market_available=crypto_market_available,
                multi_asset_market_available=multi_asset_market_available,
            )
            contracts.append(
                ActionContract(
                    index=index,
                    prompt=str(item.prompt or "").strip(),
                    plan=item.plan,
                    route=decision.route,
                    use_web=decision.use_web,
                    market_fallback=decision.market_fallback,
                    required_authorities=self._required_authorities(
                        decision.route,
                        use_web=decision.use_web,
                    ),
                    constraints=constraints,
                )
            )

        return tuple(contracts)

    @staticmethod
    def authorize(contract, granted_authorities):
        granted = {
            str(item or "").strip()
            for item in (granted_authorities or ())
            if str(item or "").strip()
        }
        missing = tuple(
            authority
            for authority in contract.required_authorities
            if authority not in granted
        )
        return ActionAuthorization(
            allowed=not missing,
            missing_authorities=missing,
        )

    def validate_many(
        self,
        contracts,
        granted_authorities=DEFAULT_HOST_AUTHORITIES,
    ):
        validated = []
        for contract in contracts:
            authorization = self.authorize(
                contract,
                granted_authorities,
            )
            if not authorization.allowed:
                missing = ", ".join(authorization.missing_authorities)
                raise PermissionError(
                    f"Action {contract.index + 1} is not authorized: {missing}"
                )
            validated.append(contract)
        return tuple(validated)
