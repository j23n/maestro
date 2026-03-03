import logging

from maestro.settings import Settings
from maestro.models import Message, LearningProfile
from maestro.rag.retrieve import embed_query, retrieve
import anthropic

logger = logging.getLogger(__name__)

settings = Settings()

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


async def get_response(user_msg: Message, context: list[Message]) -> Message:
    embedding = embed_query(user_msg.text)
    results = await retrieve(embedding, top_k=2)

    sources = ""
    for result in results:
        sources += f"[SOURCE {result.chunk.ref} - {result.similarity:0.2f} - {result.chunk.chunk_type}]\n{result.chunk.content}\n\n"

    profile = await LearningProfile.find_one()
    level_description = (
        profile.description
        if profile and profile.description
        else "The student is at approximately A2.1 level."
    )

    system = f"""You are Maestro, an expert Italian language tutor. You only speak Italian, unless clearly asked to do so in a message to explain something, then revert to Italian.

    Do not use emojis. Use lists where useful but try not to make everything one. Be supportive but no over enthusiastic. Be more brief except when generating prose for e.g. reading comprehension, which should go into depth about the given topic and have a length of ~1000 words.

    {level_description}

    Make sure to use the grammar references below to ground your answers, where applicable. When you draw on a source, cite it using markdown footnoes (e.g. "{{text refering to a rule}} [^source1]... [^source1]: [SOURCE {{ref}} {{similarity}}]: {{content}}"). If none of the sources are relevant, answer from general knowledge and say so.

    GRAMMAR REFERENCES:
    {sources}"""

    messages = [{"role": m.sender, "content": m.text} for m in context]

    logger.debug(f"Sending request: {system}\n\n{messages}")

    response = client.messages.create(
        model=settings.CHAT_MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    )

    return Message(
        text=str(response.content[0].text),
        sender="assistant",
        chat=user_msg.chat,
        in_response_to=user_msg,
    )
