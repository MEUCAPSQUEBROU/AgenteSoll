from __future__ import annotations

from openai import AsyncOpenAI

from soll.adapters.vision.base import VisionDescriber

# Mantido em português, em primeira pessoa do lead, por escolha de design do agente.
_FIRST_PERSON_PROMPT = (
    "O que há nessa imagem? Me dê a resposta como se fosse um cliente descrevendo a imagem, "
    "comece dizendo: 'te enviei uma imagem que...' Sempre em primeira pessoa, como se você fosse o cliente. "
    "Ao invés de dizer 'você me enviou', diga 'eu te enviei'."
)


class OpenAIVisionDescriber(VisionDescriber):
    def __init__(self, *, client: AsyncOpenAI, model: str = "gpt-4o-mini") -> None:
        self._client = client
        self._model = model

    async def describe(self, *, image_url: str, caption: str | None = None) -> str:
        content: list[dict[str, object]] = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": _FIRST_PERSON_PROMPT},
        ]
        if caption:
            content.append({"type": "text", "text": f"Legenda da imagem: {caption}"})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
            max_tokens=500,
        )
        return (response.choices[0].message.content or "").strip()
