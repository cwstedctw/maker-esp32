# ============================================
# 第 15 課：網頁遊戲（板子用 USB 線跟網頁說話）
# ============================================
# 學習目標：
#   - 板子每 50 毫秒從 USB 送一行狀態（JSON）給電腦，網頁讀到就能拿來玩遊戲
#   - 網頁也可以反過來送文字指令，叫板子亮燈、嗶一聲
#   - 知道「序列埠（serial port）」一次只能給一個程式用
#
# 怎麼玩：
#   1. 用「ESP32: Upload lesson (pick one)」上傳這一課
#   2. 用電腦版 Chrome 或 Edge 打開資料夾裡的 web/game.html，按「連接板子」
#   ⚠️ VS Code 的「ESP32: Serial monitor」開著時，網頁連不上（要先關掉）；
#      網頁連著時，上傳也會失敗（先在網頁按「中斷連線」）
#
# 板子 → 電腦（一行一筆，欄位名字不要改，網頁靠它們讀）：
#   {"knob":2048,"light":900,"a":0,"b":1,"key":"left"}
#   knob＝旋鈕、light＝光感測器（都是 0～4095）、a/b＝1 表示按著、
#   key＝遙控器現在按著的鍵（left/right/up/down/ok），沒按或沒記過鍵就是 ""
#
# 電腦 → 板子（一行一個指令，跟第 11 課藍牙一樣）：
#   red on / red off、yellow on / yellow off、green on / green off、
#   rgb 255 0 0（0～255）、beep、off
#
# 停止：在 Serial monitor 按 Ctrl+C
# ============================================

from lib.ezkit import *
from lib.irkeys import IRKeys
import sys
import select

# ---- 你可以改的數字 ----
SEND_FAST_MS = 50         # 狀態有變時，最快多久送一次（毫秒）
SEND_SLOW_MS = 200        # 狀態沒變時，最慢多久也要送一次（毫秒）
CHANGE = 16               # 旋鈕、光的讀數變超過多少才算「有變」（讀數本來就會小小亂跳）
OLED_MS = 250             # OLED 最快多久更新一次（送一次畫面要二三十毫秒）
BEEP_FREQ = 880           # beep 指令的音高（Hz）
BEEP_MS = 150             # beep 指令嗶多久（毫秒）

ir = IRKeys(ir_pin)       # 開始聽遙控器（會自動讀第 13 課存的 ir_keys.json）

beep_off_at = None
last_cmd = ""             # 最後收到的指令
cmd_count = 0             # 總共收到幾個指令
cmd_at = None             # 最後一次收到指令的時間


def beep(freq=BEEP_FREQ, ms=BEEP_MS):
    """開始嗶，時間到了主迴圈會關掉（不用 sleep 卡住程式）"""
    global beep_off_at
    buzzer.freq(freq)
    buzzer.duty(512)
    beep_off_at = time.ticks_add(time.ticks_ms(), ms)


def set_rgb(r, g, b):
    r, g, b = [max(0, min(255, int(v))) for v in (r, g, b)]
    np_fill(r, g, b)


def run_command(text):
    """文字指令：red on / yellow off / green on / rgb 255 0 0 / beep / off
    第三顆燈在板子上是綠色（程式裡叫 led_blue），green、blue 兩個字都收。
    回覆的字不是 JSON，網頁會自動略過；在 Serial monitor 看得到。"""
    words = text.strip().lower().split()
    if not words:
        return
    cmd = words[0]
    pins = {"red": led_red, "yellow": led_yellow, "green": led_blue, "blue": led_blue}
    if cmd in pins and len(words) > 1:
        pins[cmd].value(1 if words[1] == "on" else 0)
        reply("OK " + cmd + " " + words[1])
    elif cmd == "rgb" and len(words) == 4:
        set_rgb(words[1], words[2], words[3])
        reply("OK rgb")
    elif cmd == "beep":
        beep()
        reply("OK beep")
    elif cmd == "off":
        for p in pins.values():
            p.value(0)
        set_rgb(0, 0, 0)
        reply("OK all off")
    else:
        reply("? try: red on / green on / rgb 255 0 0 / beep / off")


def reply(text):
    ir.wait_quiet()           # 正在收遙控器訊號就等它收完（印字時程式會卡住幾毫秒）
    print(text)


# ---- 從 USB 讀指令：不等待，有字才讀 ----
# select.poll 先問「有沒有字進來」，沒有就馬上回來做別的事；Ctrl+C 一樣可以停
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
line_buf = ""


def read_commands():
    """把這一圈進來的字讀完；讀到換行就是一個完整指令。回傳收到的指令清單。"""
    global line_buf
    got = []
    for _ in range(128):                  # 一圈最多讀 128 個字，免得一直讀不完
        if not poller.poll(0):
            break
        ch = sys.stdin.read(1)
        if not ch:
            break
        if ch == "\n" or ch == "\r":
            if line_buf.strip():
                got.append(line_buf.strip())
            line_buf = ""
        elif len(line_buf) < 60:          # 太長的一行不收（不會是正常指令）
            line_buf += ch
    return got


def state_line(knob, light, a, b, key):
    """組一行 JSON。自己用 format 組，欄位順序固定、也比較省記憶體"""
    return '{{"knob":{},"light":{},"a":{},"b":{},"key":"{}"}}'.format(knob, light, a, b, key)


def draw(knob, light, a, b, key):
    oled.fill(0)
    draw_text(oled, 0, 0, "網頁連線")
    oled.text("knob {:4d}".format(knob), 0, 18, 1)
    oled.text("L{:4d} A{} B{}".format(light, a, b), 0, 28, 1)
    oled.text("key " + (key or "-"), 0, 38, 1)
    if cmd_count:
        draw_text(oled, 0, 48, "收到 " + last_cmd[:10])
    else:
        draw_text(oled, 0, 48, "等網頁連線")
    ir.show(oled)             # 用 ir.show，不要用 oled.show()（會干擾收訊號）


print("第 15 課：網頁遊戲。板子開始送資料（每 50 毫秒一行）")
if not ir.keys:
    print("沒有 ir_keys.json：遙控器的 key 會一直是空的（要用遙控器請先跑第 13 課記鍵）")

last_sent = ""
last_vals = None
sent_at = time.ticks_ms()
drawn_at = time.ticks_add(time.ticks_ms(), -OLED_MS)
need_draw = True

try:
    while True:
        now = time.ticks_ms()

        # 1) 收網頁送來的指令
        for c in read_commands():
            last_cmd = c
            cmd_count += 1
            cmd_at = now
            need_draw = True
            try:
                run_command(c)
            except Exception as e:        # 打錯字（例如 rgb a b c）不要讓整支程式停掉
                reply("? " + str(e))

        # 2) 讀狀態
        knob = potentiometer.read()
        light = light_sensor.read()
        a = 1 if btn_a.value() == 0 else 0
        b = 1 if btn_b.value() == 0 else 0
        ir.poll()                                   # 網頁要的是「按著哪個鍵」，剛按下的事件丟掉
        key = ir.name(ir.held())

        # 3) 有變就快送（最快每 50 毫秒）；沒變也至少每 200 毫秒送一次
        changed = (last_vals is None
                   or abs(knob - last_vals[0]) > CHANGE or abs(light - last_vals[1]) > CHANGE
                   or (a, b, key) != last_vals[2:])
        wait = SEND_FAST_MS if changed else SEND_SLOW_MS
        if time.ticks_diff(now, sent_at) >= wait:
            line = state_line(knob, light, a, b, key)
            ir.wait_quiet()                         # 正在收遙控器訊號就等它收完再印
            print(line)
            sent_at = time.ticks_ms()               # 用印完的時間算，下一行才不會靠太近
            if changed:
                last_vals = (knob, light, a, b, key)
                need_draw = True

        # 4) 嗶聲時間到了就關
        if beep_off_at is not None and time.ticks_diff(now, beep_off_at) >= 0:
            buzzer.duty(0)
            beep_off_at = None

        # 5) OLED：有變化、而且離上次夠久才畫
        if need_draw and time.ticks_diff(now, drawn_at) >= OLED_MS:
            draw(knob, light, a, b, key)
            drawn_at = now
            need_draw = False

        time.sleep_ms(5)
finally:
    buzzer.duty(0)
    ir.stop()
