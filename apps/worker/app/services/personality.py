from typing import Any


PERSONALITY_PROMPT = """
You are an expert psychologist and career counselor.

Based on the following survey responses, analyze the person's personality
and return a JSON object with these exact fields:

{{
    "mbti": "one of 16 MBTI types e.g. INTJ",
    "big_five": {{
        "openness": 0.0-1.0,
        "conscientiousness": 0.0-1.0,
        "extraversion": 0.0-1.0,
        "agreeableness": 0.0-1.0,
        "neuroticism": 0.0-1.0
    }},
    "strengths": ["strength1", "strength2", "strength3"],
    "blind_spots": ["blindspot1", "blindspot2"],
    "summary": "2-3 sentence personality summary"
}}

Survey responses:
{responses}

Return ONLY the JSON object, no other text.
"""


async def score_personality(
    fields: list[dict[str, Any]],
    anthropic_client: Any,
) -> dict:
    responses = "\n".join(f"Q: {f['label']}\nA: {f['value']}" for f in fields)

    message = await anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": PERSONALITY_PROMPT.format(responses=responses),
            }
        ],
    )

    import json

    return json.loads(message.content[0].text)
