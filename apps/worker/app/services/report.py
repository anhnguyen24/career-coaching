from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
OUTPUT_DIR = Path("/tmp/career-coaching")


def get_jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def render_template(template_name: str, context: dict) -> str:
    env = get_jinja_env()
    template = env.get_template(template_name)
    return template.render(**context)


def generate_pdf(result_data: dict, output_path: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    context = {
        "name": result_data.get("name"),
        "date": datetime.now().strftime("%B %d, %Y"),
        "personality": result_data["personality_scores"],
        "careers": result_data["career_matches"],
    }

    html_content = render_template("report.html", context)
    output_file = OUTPUT_DIR / output_path

    HTML(string=html_content).write_pdf(str(output_file))

    return str(output_file)
