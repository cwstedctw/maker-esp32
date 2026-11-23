# ============================================
# 第 13 課：遙控器學習機（紅外線認鍵）
# ============================================
# 學習目標：
#   - 知道遙控器的每個鍵都有自己的「按鍵碼」（一個號碼）
#   - 讓板子把五個鍵（左、右、上、下、確定）記起來，存成板子上的 ir_keys.json
#   - 用遙控器控制彩色燈：左右鍵換顏色、上下鍵調亮度、確定鍵嗶一聲
#
# 怎麼玩：
#   1. 按遙控器任何一個鍵 → OLED 顯示這個鍵的號碼，和這是第幾次按
#      （按住不放不會一直加：遙控器按住時送的是「重複碼」，不算新的一次）
#   2. 按住板子的 A 鍵一秒 → 進入「記鍵」：照螢幕依序按 左、右、上、下、確定
#      記錯了？再按住 A 一秒，從頭重記一次
#   3. 記好之後：左右換顏色、上下調亮度（按住會一直調）、確定嗶一聲
#
# 你會學到：
#   - lib/irkeys.py 怎麼用：ir.poll()（剛按下）、ir.held()（還按著）
#   - 用 json 把資料存在板子上，下次開機還在（第 14、15 課會讀這個檔）
#
# 停止：在 Serial monitor 按 Ctrl+C
# ============================================

from lib.ezkit import *
from lib.irkeys import IRKeys, load_keys, save_keys, code_text, KEY_NAMES

# ---- 你可以改的數字 ----
LONG_PRESS_MS = 1000      # 按住 A 多久算「長按」（毫秒）
REPEAT_MS = 150           # 按住上下鍵時，每隔多久調一次亮度（毫秒）
REPEAT_DELAY_MS = 400     # 按住上下鍵多久之後才開始連續調（毫秒）
MAX_BRIGHT = 0.4          # 彩色燈最亮到幾成（1.0＝全亮，很刺眼）
BEEP_FREQ = 1046          # 確定鍵的嗶聲音高（Hz）

# 顏色清單：(OLED 上顯示的字, (紅, 綠, 藍))
COLORS = [
    ("紅", (255, 0, 0)),
    ("黃", (255, 160, 0)),
    ("綠", (0, 255, 0)),
    ("青", (0, 255, 255)),
    ("藍", (0, 0, 255)),
    ("紫", (160, 0, 255)),
    ("白", (255, 255, 255)),
]

# 五個鍵在 OLED 上的名字（順序跟 KEY_NAMES 一樣：left right up down ok）
KEY_LABELS = {"left": "左", "right": "右", "up": "上", "down": "下", "ok": "確定"}

ir = IRKeys(ir_pin)            # 開始聽遙控器（會自動讀 ir_keys.json）

counts = {}                    # 每個鍵碼按了幾次
learning = -1                  # -1＝沒在記鍵；0～4＝正在記第幾個鍵
learned = {}                   # 記鍵時暫存
color_i = 0                    # 現在是第幾個顏色
bright = 3                     # 亮度 1～5
last_code = None               # 最後按的鍵碼
note = ""                      # OLED 最下面一行要顯示的字
need_draw = True               # 畫面要不要重畫
beep_off_at = None             # 嗶聲什麼時候關（毫秒）


def beep(freq=BEEP_FREQ, ms=80):
    """開始嗶，時間到了主迴圈會關掉（不用 sleep 卡住程式）"""
    global beep_off_at
    buzzer.freq(freq)
    buzzer.duty(512)
    beep_off_at = time.ticks_add(time.ticks_ms(), ms)


def update_light():
    name, (r, g, b) = COLORS[color_i]
    k = MAX_BRIGHT * bright / 5
    np_fill(int(r * k), int(g * k), int(b * k))


def draw():
    oled.fill(0)
    if learning >= 0:
        draw_text(oled, 0, 0, "記鍵 {}/5".format(learning + 1))
        draw_text(oled, 0, 16, "請按 " + KEY_LABELS[KEY_NAMES[learning]])
        draw_text(oled, 0, 32, note)
        draw_text(oled, 0, 48, "A按一秒 重來")
    else:
        draw_text(oled, 0, 0, "紅外線遙控")
        if last_code is None:
            draw_text(oled, 0, 16, "按遙控器的鍵")
        else:
            oled.text(code_text(last_code), 0, 20, 1)
            label = KEY_LABELS.get(ir.name(last_code), "")
            draw_text(oled, 0, 32, "第{}次 {}".format(counts.get(last_code, 0), label))
        if note:
            draw_text(oled, 0, 48, note)
        elif not ir.keys:
            draw_text(oled, 0, 48, "A按一秒 記鍵")
    ir.show(oled)              # 用 ir.show，不要用 oled.show()（會干擾收訊號）


def start_learning():
    global learning, learned, note
    learning = 0
    learned = {}
    note = ""
    beep(880, 120)
    print("開始記鍵：請依序按 左、右、上、下、確定")


def learn_key(code):
    """記鍵模式下按了一個鍵"""
    global learning, note
    if code in learned.values():
        note = "這鍵已用了"
        beep(220, 200)
        return
    name = KEY_NAMES[learning]
    learned[name] = code
    print("記好了：", name, "=", code_text(code))
    beep(1318, 60)
    note = ""
    learning += 1
    if learning >= len(KEY_NAMES):
        save_keys(learned)
        ir.keys = dict(learned)
        learning = -1
        note = "記好了 已存檔"
        print("五個鍵都記好了，已存成 ir_keys.json：", learned)
        update_light()


def use_key(code):
    """一般模式下按了一個鍵：照鍵名做事"""
    global color_i, bright, note
    name = ir.name(code)
    if name == "left":
        color_i = (color_i - 1) % len(COLORS)
    elif name == "right":
        color_i = (color_i + 1) % len(COLORS)
    elif name == "up":
        bright = min(5, bright + 1)
    elif name == "down":
        bright = max(1, bright - 1)
    elif name == "ok":
        beep()
    if name:
        update_light()
        note = "顏色{} 亮度{}".format(COLORS[color_i][0], bright)


print("=== 第 13 課：遙控器學習機 ===")
if ir.keys:
    print("讀到記好的鍵：", ir.keys)
    update_light()
else:
    print("還沒記過鍵：按住 A 一秒開始記")

a_down_at = None               # A 從什麼時候開始按著
a_fired = False                # 這次長按已經處理過了嗎
hold_since = None              # 上／下鍵從什麼時候開始按著
last_repeat = 0

try:
    while True:
        now = time.ticks_ms()

        # 1) 遙控器：剛按下的鍵（重複碼不會出現在這裡）
        code = ir.poll()
        if code is not None:
            if learning >= 0:
                learn_key(code)
            else:
                counts[code] = counts.get(code, 0) + 1
                last_code = code
                note = ""
                kind = ir.last_kind
                print("按鍵碼 {}  第 {} 次  （{}）{}".format(
                    code_text(code), counts[code], kind, "  ＝" + ir.name(code) if ir.name(code) else ""))
                beep(1568, 30)
                use_key(code)
            need_draw = True

        # 2) 遙控器：按住上／下鍵不放 → 連續調亮度
        h = ir.held()
        if learning < 0 and h is not None and ir.name(h) in ("up", "down"):
            if hold_since is None:
                hold_since = now
            elif (time.ticks_diff(now, hold_since) > REPEAT_DELAY_MS
                  and time.ticks_diff(now, last_repeat) > REPEAT_MS):
                last_repeat = now
                use_key(h)
                need_draw = True
        else:
            hold_since = None

        # 3) 板子的 A 鍵：按住一秒 → 開始（或重新開始）記鍵
        if btn_a.value() == 0:
            if a_down_at is None:
                a_down_at = now
                a_fired = False
            elif not a_fired and time.ticks_diff(now, a_down_at) >= LONG_PRESS_MS:
                a_fired = True
                start_learning()
                need_draw = True
        else:
            a_down_at = None

        # 4) 嗶聲時間到了就關
        if beep_off_at is not None and time.ticks_diff(now, beep_off_at) >= 0:
            buzzer.duty(0)
            beep_off_at = None

        # 5) 有變化才重畫（OLED 送一次畫面要二三十毫秒，不要每圈都畫）
        if need_draw:
            draw()
            need_draw = False

        time.sleep_ms(20)
finally:
    buzzer.duty(0)
    np_clear()
    ir.stop()
