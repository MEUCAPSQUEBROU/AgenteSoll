from __future__ import annotations

from abc import ABC, abstractmethod


class VisionDescriber(ABC):
    @abstractmethod
    async def describe(self, *, image_url: str, caption: str | None = None) -> str:
        """Descreve a imagem em primeira pessoa, como se o lead a estivesse descrevendo."""
