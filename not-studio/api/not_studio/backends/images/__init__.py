"""Local image-generation providers."""

from .flux2_klein import generate_cover, preload_model

__all__ = ["generate_cover", "preload_model"]
