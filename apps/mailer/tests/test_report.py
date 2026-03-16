from app.services.report import render_template


SAMPLE_RESULT = {
    "name": "John Smith",
    "personality_scores": {
        "mbti": "INTJ",
        "big_five": {
            "openness": 0.85,
            "conscientiousness": 0.75,
            "extraversion": 0.30,
            "agreeableness": 0.60,
            "neuroticism": 0.25,
        },
        "strengths": ["Strategic thinking", "Problem solving"],
        "blind_spots": ["Perfectionism"],
        "summary": "A strategic thinker who excels at complex problem solving.",
    },
    "career_matches": {
        "careers": [
            {
                "title": "Software Architect",
                "fit_score": 0.92,
                "reason": "Matches analytical nature",
                "required_skills": ["Python", "System Design"],
                "growth_outlook": "positive",
            }
        ],
        "action_steps": ["Build portfolio", "Get certified"],
    },
}


def test_render_report_template():
    """Report template renders without errors"""
    from datetime import datetime

    html = render_template(
        "report.html",
        {
            "name": SAMPLE_RESULT["name"],
            "date": datetime.now().strftime("%B %d, %Y"),
            "personality": SAMPLE_RESULT["personality_scores"],
            "careers": SAMPLE_RESULT["career_matches"],
        },
    )
    assert "INTJ" in html
    assert "Software Architect" in html
    assert "Strategic thinking" in html


def test_render_infographic_template():
    """Infographic template renders without errors"""
    from datetime import datetime
    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path

    templates_dir = Path(__file__).parent.parent / "app" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("infographic.html")

    html = template.render(
        name=SAMPLE_RESULT["name"],
        date=datetime.now().strftime("%B %d, %Y"),
        personality=SAMPLE_RESULT["personality_scores"],
        careers=SAMPLE_RESULT["career_matches"],
    )
    assert "INTJ" in html
    assert "Software Architect" in html
