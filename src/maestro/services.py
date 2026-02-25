from maestro.settings import Settings
from typing import List
from maestro.models import Message
from maestro.rag.retrieve import embed_query, retrieve
import anthropic

settings = Settings()

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


async def get_response(user_msg: Message, context: List[Message]) -> Message:
    embedding = embed_query(user_msg.text)
    results = retrieve(embedding, top_k=2)

    sources = ""
    for result in results:
        sources += f"[SOURCE {result.chunk.ref} - {result.similarity:0.2f} - {result.chunk.chunk_type}]\n{result.chunk.content}\n\n"

    system = f"""You are Maestro, an expert Italian language tutor. You only speak Italian, unless clearly asked to do so in a message to explain something, then revert to Italian.

    Use emoji's only where necessary. Use lists where useful but try not to make everything one. Be supportive but no over enthusiastic. Be more brief except when generating prose for e.g. reading comprehension, which should go into depth about the given topic and have a length of ~1000 words.
    
    Make sure to use the grammar references below to ground your answers, where applicable. When you draw on a source, cite it using markdown footnoes (e.g. "{{text refering to a rule}} [^source1]... [^source1]: [SOURCE {{ref}} {{similarity}}]: {{content}}"). If none of the sources are relevant, answer from general knowledge and say so.

    GRAMMAR REFERENCES:
    {sources}"""

    messages = [{"role": m.sender, "content": m.text} for m in context] + [
        {"role": user_msg.sender, "content": user_msg.text}
    ]

    # return Message(
    #     text="AI reply",
    #     sender="assistant",
    #     chat_id=user_msg.chat_id,
    #     in_response_to_id=user_msg.id,
    # )

    print(f"Sending request: {system}\n\n{messages}")

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        messages=messages,
    )

    return Message(
        text=str(response.content[0].text),
        sender="assistant",
        chat_id=user_msg.chat_id,
        in_response_to_id=user_msg.id,
    )
