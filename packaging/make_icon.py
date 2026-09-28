"""从内置默认皮肤的待机帧制作 DeskPet 图标。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sprites" / "idle_1.png"
PREVIEW = ROOT / "packaging" / "DeskPet-icon.png"


def make_icon() -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    # 固定裁切范围取头肩，不重新绘制角色。
    # 原动画画布给右侧留了大量透明空间；按人物实际占用的左半部裁切。
    portrait = source.crop((0, 0, 240, 240))
    portrait = portrait.resize((900, 900), Image.Resampling.LANCZOS)
    alpha = portrait.getchannel("A")
    for y in range(780, 900):
        fade = (900 - y) / 120
        for x in range(900):
            alpha.putpixel((x, y), round(alpha.getpixel((x, y)) * fade))
    portrait.putalpha(alpha)

    icon = Image.new("RGBA", (1024, 1024))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((24, 24, 1000, 1000), radius=225,
                           fill=(76, 103, 142, 255))

    shadow = Image.new("RGBA", icon.size)
    shadow.alpha_composite(portrait, (87, 90))
    alpha = shadow.getchannel("A").filter(ImageFilter.GaussianBlur(18))
    shadow.putalpha(alpha.point(lambda value: round(value * 0.23)))
    icon.alpha_composite(shadow)
    icon.alpha_composite(portrait, (87, 72))
    return icon


def main() -> None:
    icon = make_icon()
    icon.save(PREVIEW)
    print(PREVIEW)


if __name__ == "__main__":
    main()
