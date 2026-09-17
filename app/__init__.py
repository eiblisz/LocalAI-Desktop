from . import web_search_tool as _web_search_tool
from .shopping_search_patch import install_shopping_search_patch as _install_shopping_search_patch

_install_shopping_search_patch(_web_search_tool)

del _install_shopping_search_patch
del _web_search_tool

from . import evidence_verifier as _evidence_verifier
from .answer_verifier_patch import (
    install_answer_price_equivalence_patch as _install_answer_price_equivalence_patch,
)
from .price_evidence_patch import (
    install_price_evidence_patch as _install_price_evidence_patch,
)

_install_price_evidence_patch(_evidence_verifier)
_install_answer_price_equivalence_patch(_evidence_verifier)

del _install_price_evidence_patch
del _install_answer_price_equivalence_patch
del _evidence_verifier

from . import workers as _workers
from .verified_fallback_patch import (
    install_verified_fallback_patch as _install_verified_fallback_patch,
)
from .bilingual_search_patch import (
    install_bilingual_search_patch as _install_bilingual_search_patch,
)

_install_verified_fallback_patch(_workers)
_install_bilingual_search_patch(_workers)

del _install_verified_fallback_patch
del _install_bilingual_search_patch
del _workers

from . import main_window as _main_window
from .vram_release_patch import (
    install_vram_release_patch as _install_vram_release_patch,
)

_install_vram_release_patch(_main_window)

del _install_vram_release_patch
del _main_window
