import asyncio, os
from playwright.async_api import async_playwright

DIR = '/home/z/my-project/docs/diagrams'
OUT = '/home/z/my-project/public/diagrams'

JOBS = [
    ('01-system-architecture.html', '01-system-architecture.png', 1280),
    ('02-information-architecture.html', '02-information-architecture.png', 1500),
    ('03-api-surface-map.html', '03-api-surface-map.png', 1300),
    ('04-data-model-overview.html', '04-data-model-overview.png', 1400),
    ('05-decision-pipeline.html', '05-decision-pipeline.png', 1200),
    ('06-deployment-topology.html', '06-deployment-topology.png', 1350),
    ('07-request-lifecycle.html', '07-request-lifecycle.png', 1600),
    ('08-soil-science-pipeline.html', '08-soil-science-pipeline.png', 1220),
    ('09-data-governance.html', '09-data-governance.png', 1320),
    ('10-role-journey.html', '10-role-journey.png', 1560),
    ('11-tech-stack.html', '11-tech-stack.png', 1430),
    ('12-security-architecture.html', '12-security-architecture.png', 1280),
]

async def render(page, html_name, png_name, width):
    html_path = os.path.join(DIR, html_name)
    output_path = os.path.join(OUT, png_name)
    await page.set_viewport_size({'width': width, 'height': 900})
    await page.goto(f'file://{html_path}', wait_until='networkidle')
    await page.wait_for_timeout(500)
    el = page.locator('#root, #mindmap').first
    bbox = await el.bounding_box()
    if bbox:
        fit_w = max(width, int(bbox['width'] + 100))
        fit_h = int(bbox['height'] + 100)
        await page.set_viewport_size({'width': fit_w, 'height': fit_h})
        await page.wait_for_timeout(300)
        bbox = await el.bounding_box()
    await el.screenshot(path=output_path)
    print(f'OK {png_name} ({os.path.getsize(output_path)/1024:.0f} KB, bbox {bbox["width"]:.0f}x{bbox["height"]:.0f})')

async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=2)
        for html_name, png_name, width in JOBS:
            try:
                await render(page, html_name, png_name, width)
            except Exception as e:
                print(f'FAIL {html_name}: {e}')
        await browser.close()

asyncio.run(main())
