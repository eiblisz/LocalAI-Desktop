from . import web_search_tool as _web_search_tool
from .shopping_search_patch import install_shopping_search_patch as _install_shopping_search_patch

_install_shopping_search_patch(_web_search_tool)

del _install_shopping_search_patch
del _web_search_tool

from . import evidence_verifier as _evidence_verifier
from .answer_verifier_patch import (
    install_answer_price_equivalence_patch as _install_answer_price_equivalence_patch,
)

_install_answer_price_equivalence_patch(_evidence_verifier)

del _install_answer_price_equivalence_patch
del _evidence_verifier

from . import workers as _workers
from .verified_fallback_patch import (
    install_verified_fallback_patch as _install_verified_fallback_patch,
)

_install_verified_fallback_patch(_workers)

del _install_verified_fallback_patch
del _workers
