from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
OUTPUT_DIR = Path("/tmp/career-coaching")


def get_jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


async def generate_infographic(result_data: dict, output_path: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    env = get_jinja_env()
    template = env.get_template("infographic.html")

    context = {
        "name": result_data.get("name"),
        "date": datetime.now().strftime("%B %d, %Y"),
        "personality": result_data["personality_scores"],
        "careers": result_data["career_matches"],
    }

    html_content = template.render(**context)
    output_file = OUTPUT_DIR / output_path

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 800, "height": 1000})
        await page.set_content(html_content, wait_until="networkidle")
        await page.screenshot(path=str(output_file), full_page=False)
        await browser.close()

    return str(output_file)
