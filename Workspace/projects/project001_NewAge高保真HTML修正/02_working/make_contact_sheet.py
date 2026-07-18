from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "02_working" / "browser_all"
images = [Image.open(path).convert("RGB") for path in sorted(SOURCE.glob("page_*.png"))]
thumb_width = 306
thumb_height = 396
cell_width = thumb_width + 24
cell_height = thumb_height + 42
columns = 3
rows = (len(images) + columns - 1) // columns
sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#303030")
draw = ImageDraw.Draw(sheet)
for index, image in enumerate(images):
    image.thumbnail((thumb_width, thumb_height))
    x = (index % columns) * cell_width + 12
    y = (index // columns) * cell_height + 30
    sheet.paste(image, (x, y))
    draw.text((x, 8 + (index // columns) * cell_height), f"HTML page {index + 1}", fill="white")
sheet.save(ROOT / "02_working" / "contact_sheet_fixed.png")
