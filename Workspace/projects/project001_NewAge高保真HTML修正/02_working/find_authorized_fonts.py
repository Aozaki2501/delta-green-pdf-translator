from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


root = Path(r"K:\qq下载\FONTS")
keywords = ("fandol", "兰亭", "刊黑", "牟氏", "美隶", "方正", "lanting", "meili")


def names(font: TTFont) -> set[str]:
    result = set()
    for record in font["name"].names:
        if record.nameID not in {1, 2, 4, 6, 16, 17}:
            continue
        try:
            result.add(record.toUnicode())
        except UnicodeDecodeError:
            continue
    return result


for path in root.rglob("*"):
    if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        continue
    try:
        fonts = TTCollection(path).fonts if path.suffix.lower() == ".ttc" else [TTFont(path, lazy=True)]
        font_names = sorted({name for font in fonts for name in names(font)})
    except Exception:
        continue
    searchable = " ".join([path.name, *font_names]).lower()
    if any(keyword.lower() in searchable for keyword in keywords):
        print(path)
        print("  " + " | ".join(font_names))
