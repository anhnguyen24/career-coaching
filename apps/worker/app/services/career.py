from typing import Any


CAREER_PROMPT = """
You are an expert career counselor with deep knowledge of occupations.

Based on the following personality profile, suggest the top 5 career matches
and return a JSON object with this exact structure:

{{
    "careers": [
        {{
            "title": "Career Title",
            "fit_score": 0.0-1.0,
            "reason": "Why this career suits them",
            "required_skills": ["skill1", "skill2"],
            "growth_outlook": "positive/stable/declining"
        }}
    ],
    "action_steps": [
        "Concrete step 1",
        "Concrete step 2",
        "Concrete step 3"
    ]
}}

Personality profile:
{personality}

Return ONLY the JSON object, no other text.
"""


async def match_careers(
    personality: dict,
    anthropic_client: Any,
) -> dict:
    import json

    message = await anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": CAREER_PROMPT.format(
                    personality=json.dumps(personality, indent=2)
                ),
            }
        ],
    )

    return json.loads(message.content[0].text)
