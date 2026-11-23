"""
在電腦上執行，產生 zhfont.py 給 ESP32 使用。
用 Pillow 把中文字渲染成 16x16 點陣圖資料。

- 已經在 zhfont.py 裡的字，點陣資料原封不動沿用（只產生新加進 CHARS 的字），
  所以換一台電腦、換一種字型也不會讓舊字變樣。要全部重畫：python tools/gen_font.py --all
- 字型：Windows 用微軟正黑體；Mac 沒有正黑體，改用 macOS 內建的蘋方（PingFang TC）。
"""
from PIL import Image, ImageDraw, ImageFont
import ast
import glob
import os
import sys

# 需要用到的所有中文字（新字加在最後面）
CHARS = "展示開始紅黃藍燈彩虹蜂鳴器音階感測溫度濕光線按鈕繼電完成準備讀取中呼吸亮控制旋調互動外遙模式等秒進條閃爍漸變歡迎全功能效果轉收信號部小星或接到重來色同時停第課選單上下執行你好世界三不也了些以們做偵可各合喀因圖在型基奏字學己形我手文曲會有本檔次歌沒混演為用的緣聲聽自英裡要試這遮邊關顆顏顯綠青紫白機連已網頁牙密碼址請斷傳送訊息一估健再出分列危名品埠填失子害對常序康後所打抓推敏敗料族普東板氣看程稍稱空群臺良花蓮資質通還鐘非左右確定鍵記存球數"

# Windows 內建微軟正黑體
FONT_PATH = "C:/Windows/Fonts/msjh.ttc"
FONT_SIZE = 15  # 配合 16x16 格子，稍大避免筆畫太細

# 找不到微軟正黑體時（例如 Mac），依序試這些字型；(路徑, 要找的字型名稱)
FALLBACK_FONTS = (
    ["/System/Library/Fonts/PingFang.ttc"]
    + sorted(glob.glob("/System/Library/AssetsV2/*/*/AssetData/PingFang.ttc")),
    "PingFang TC",
)
LAST_RESORT = ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]

OUT_FILE = "zhfont.py"                      # 產生在資料夾最上層，再複製到 esp32/lib/zhfont.py
OLD_FILES = ["zhfont.py", "esp32/lib/zhfont.py"]


def load_font():
    """回傳 (字型, 說明文字)"""
    if os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, FONT_SIZE), FONT_PATH
    paths, family = FALLBACK_FONTS
    for path in paths:
        if not os.path.exists(path):
            continue
        for i in range(40):                 # .ttc 裡有好幾種字型，挑「PingFang TC 一般粗細」
            try:
                f = ImageFont.truetype(path, FONT_SIZE, index=i)
            except OSError:
                break
            if f.getname() == (family, "Regular"):
                return f, "{} #{}（{}）".format(path, i, family)
    for path in LAST_RESORT:
        if os.path.exists(path):
            return ImageFont.truetype(path, FONT_SIZE), path
    sys.exit("找不到中文字型：Windows 要有 C:/Windows/Fonts/msjh.ttc，Mac 要有蘋方或黑體")


def load_old_font():
    """讀現有 zhfont.py 的 FONT（不執行它，只把字典讀出來）"""
    for path in OLD_FILES:
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FONT":
                return ast.literal_eval(node.value), path
    return {}, None


def char_to_bitmap(ch, font):
    img = Image.new("1", (16, 16), 0)
    draw = ImageDraw.Draw(img)
    bbox = font.getbbox(ch)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (16 - w) // 2 - bbox[0]
    y = (16 - h) // 2 - bbox[1]
    draw.text((x, y), ch, fill=1, font=font)
    # 轉成 bytes: 每行 2 bytes, 共 16 行 = 32 bytes
    data = bytearray(32)
    for row in range(16):
        val = 0
        for col in range(16):
            if img.getpixel((col, row)):
                val |= 1 << (15 - col)
        data[row * 2] = (val >> 8) & 0xFF
        data[row * 2 + 1] = val & 0xFF
    return bytes(data)


def main():
    font, font_name = load_font()
    old, old_path = ({}, None) if "--all" in sys.argv else load_old_font()
    reused = [ch for ch in CHARS if ch in old]
    new = [ch for ch in CHARS if ch not in old]
    print("字型：", font_name)
    if old_path:
        print("沿用 {} 裡的 {} 個字（點陣不變）".format(old_path, len(reused)))
    print("新產生 {} 個字：{}".format(len(new), "".join(new)))
    lines = []
    lines.append("# Auto-generated Chinese bitmap font (16x16)")
    lines.append("# Do not edit manually")
    lines.append("")
    lines.append("FONT = {")
    for ch in CHARS:
        bmp = old[ch] if ch in old else char_to_bitmap(ch, font)
        lines.append("    {}: {},".format(repr(ch), repr(bmp)))
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def draw_text(oled, x, y, text):")
    lines.append('    """在 OLED 上繪製中文字串，每字 16x16"""')
    lines.append("    for ch in text:")
    lines.append("        if ch in FONT:")
    lines.append("            data = FONT[ch]")
    lines.append("            for row in range(16):")
    lines.append("                val = (data[row * 2] << 8) | data[row * 2 + 1]")
    lines.append("                for col in range(16):")
    lines.append("                    if val & (1 << (15 - col)):")
    lines.append("                        oled.pixel(x + col, y + row, 1)")
    lines.append("            x += 16")
    lines.append("        elif ch == ' ':")
    lines.append("            x += 8")
    lines.append("        else:")
    lines.append("            # ASCII fallback: use built-in font")
    lines.append("            oled.text(ch, x, y + 4, 1)")
    lines.append("            x += 8")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("Generated zhfont.py with {} characters".format(len(CHARS)))


if __name__ == "__main__":
    main()
