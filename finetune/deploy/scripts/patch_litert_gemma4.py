#!/usr/bin/env python3
"""
FT-F2: Idempotent monkey-patch for litert-torch 0.9.1's Gemma4 cache layer.

Adds the missing ``get_max_length`` method to ``LiteRTLMCacheLayer`` so that
``LiteRTLMCacheLayerForGemma4`` can be instantiated during model export.

Background
----------
``CacheLayerMixin`` (transformers) declares ``get_max_length`` as
``@abstractmethod``.  ``LiteRTLMCacheLayer`` inherits via
``LiteRTLMCacheLayerMixin`` but never overrides it, nor does the Gemma4
subclass.  This patch provides a concrete implementation that reads the max
length from the key-cache tensor's last dimension (falling back to -1 when
the cache hasn't been initialised).

Run BEFORE any litert_torch export::

    python3 patch_litert_gemma4.py        # applies the patch
    python3 -m litert_torch.generative.export_hf export ...   # actual export

Idempotent — safe to run multiple times.
"""

import sys
from typing import Any

TARGET_PKG_BASE = "litert_torch.generative.export_hf.core.cache"
TARGET_PKG_GEMMA4 = "litert_torch.generative.export_hf.model_ext.gemma4.cache"


def _get_max_length_impl(self) -> int:
    """Return the maximum sequence length this cache layer can hold.

    Priority order:
      1. ``max_cache_len`` attribute (set during export config) — this is
         the authoritative configured value, always valid.
      2. Last dimension of the key-cache tensor (runtime inference).
      3. -1 as a safe fallback (undefined / dynamic cache).

    During ``torch.export`` tracing the key-cache may be an empty or fake
    tensor whose shape is 0 or symbolic, which causes downstream ops like
    ``torch.arange(-1)`` to fail.  Always prefer ``max_cache_len``.
    """
    max_cache_len = getattr(self, "max_cache_len", None)
    if max_cache_len is not None:
        return max_cache_len
    for attr in ("key_cache", "k_cache"):
        obj = getattr(self, attr, None)
        if obj is not None:
            return obj.shape[-1]
    return -1


def _is_patched(cls: type) -> bool:
    """Check if *this specific class* already has get_max_length in __dict__."""
    return "get_max_length" in cls.__dict__


def _clear_abstractmethods(cls: type) -> None:
    """Force-clear ``__abstractmethods__`` on *cls* via ABCMeta's setattr.

    ABCMeta caches ``__abstractmethods__`` as a frozenset at class-creation
    time.  When we ``setattr`` a concrete method onto a parent, ABCMeta's
    ``__setattr__`` calls ``_abc_clear_abstractmethods`` which *should*
    recompute the set for the class and all its subclasses, but CPython's
    caching can leave stale entries on child classes.  Explicitly clearing
    on every affected class is the only reliable approach.

    Uses ``type(cls).__setattr__`` so ABCMeta's value-normalisation (rather
    than ``object.__setattr__`` which bypasses it entirely) is preserved
    while still going through the metaclass descriptor protocol.
    """
    type(cls).__setattr__(cls, "__abstractmethods__", frozenset())


def patch() -> bool:
    """Apply the ``get_max_length`` monkey-patch.

    Patches **both** the base ``LiteRTLMCacheLayer`` and the Gemma4 subclass
    ``LiteRTLMCacheLayerForGemma4``, then clears ``__abstractmethods__`` on
    **both** classes so Python's ABC machinery does not block instantiation.

    Returns ``True`` if the patch was applied, ``False`` if already present.
    """
    from litert_torch.generative.export_hf.core import cache as cache_lib
    from litert_torch.generative.export_hf.model_ext.gemma4 import cache as gemma4_cache

    base_cls = cache_lib.LiteRTLMCacheLayer
    gemma4_cls = gemma4_cache.LiteRTLMCacheLayerForGemma4
    applied = False

    # --- patch the parent (LiteRTLMCacheLayer) -----------------------------
    if not _is_patched(base_cls):
        fn = _get_max_length_impl
        fn.__qualname__ = "LiteRTLMCacheLayer.get_max_length"
        fn.__module__ = TARGET_PKG_BASE
        fn.__doc__ = _get_max_length_impl.__doc__
        setattr(base_cls, "get_max_length", fn)
        _clear_abstractmethods(base_cls)
        applied = True

    # --- patch the Gemma4 subclass directly, then clear abstractmethods ----
    if not _is_patched(gemma4_cls):
        fn = _get_max_length_impl
        fn.__qualname__ = "LiteRTLMCacheLayerForGemma4.get_max_length"
        fn.__module__ = TARGET_PKG_GEMMA4
        fn.__doc__ = _get_max_length_impl.__doc__
        setattr(gemma4_cls, "get_max_length", fn)
        _clear_abstractmethods(gemma4_cls)
        applied = True

    # --- verify ------------------------------------------------------------
    base_abstract = getattr(base_cls, "__abstractmethods__", frozenset())
    gemma_abstract = getattr(gemma4_cls, "__abstractmethods__", frozenset())
    if not base_abstract and not gemma_abstract:
        print(
            f"[patch] ✓ get_max_length added to {base_cls.__name__}"
            f" and {gemma4_cls.__name__}"
            f" — both cache layers are now concrete"
        )
    else:
        if base_abstract:
            print(
                f"[patch] ⚠ {base_cls.__name__} still abstract:"
                f" {base_abstract}"
            )
        if gemma_abstract:
            print(
                f"[patch] ⚠ {gemma4_cls.__name__} still abstract:"
                f" {gemma_abstract}"
            )
        return False

    return applied


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        applied = patch()
    except ImportError as exc:
        print(f"[patch] ERROR — is litert-torch installed?  {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[patch] ERROR — {exc}")
        sys.exit(2)

    if applied:
        print("\n[patch] Done — safe to import export modules.")
    else:
        print("\n[patch] Already patched — no changes made.")
    sys.exit(0)
