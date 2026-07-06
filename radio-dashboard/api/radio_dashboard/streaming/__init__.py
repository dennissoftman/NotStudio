"""Real-time playout + encoding (feature #3).

A per-stream :class:`PlayoutEngine` reads ready buffer segments in real time and
fans PCM frames out to consumers: per-listener HTTP MP3, a rolling HLS playlist,
and an optional Icecast publisher.
"""

from .playout import PlayoutManager  # noqa: F401
