from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGB", (400, 200), (255, 255, 255))
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("C:\\Windows\\Fonts\\arialbd.ttf", 120)
except Exception:
    font = ImageFont.load_default()
d.text((60, 30), "7391", fill=(0, 0, 0), font=font)
img.save(r"D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\logs\v6\_vtest.png")
print("saved _vtest.png")
