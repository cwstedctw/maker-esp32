# ============================================
# 第 11 課：藍牙遙控（BLE，手機 App 控制板子）
# ============================================
# 學習目標：
#   - 讓 ESP32 當一個「藍牙低功耗（BLE）裝置」，手機掃得到、連得上
#   - 手機按開關 → 板子的紅燈亮滅；按板子的 A 鍵 → 手機畫面跟著變
#   - 手機傳一行文字指令（例如 rgb 255 0 0）→ 板子照做
#
# 手機要裝的 App（都免費，iPhone、Android 都有）：
#   - nRF Blinky（最簡單）：一個 LED 開關＋一個按鈕狀態
#   - nRF Connect 或 LightBlue：可以傳文字指令（UART）
#   ⚠️ 不要從手機「設定 → 藍牙」配對，要在 App 裡面掃描、連線
#
# 板子提供兩組「服務」（service）：
#   1. LED 與按鈕服務（Nordic LBS）：nRF Blinky 用這組
#   2. 文字指令服務（Nordic UART）：傳 "red on"、"green on"、"rgb 0 0 255"、"beep" 這種指令
#
# 你會學到：
#   - BLE 的裝置名稱、服務、特徵值（characteristic）是什麼
#   - 「寫入」（手機 → 板子）跟「通知」（板子 → 手機）兩個方向
#
# 停止：在 Serial monitor 按 Ctrl+C
# ============================================

from lib.ezkit import *
import bluetooth
import struct
import machine
from micropython import const

BOARD_ID = "".join("{:02X}".format(b) for b in machine.unique_id()[-2:])
NAME = "maker-" + BOARD_ID              # 手機上看到的名字

# ---- BLE 事件代碼（MicroPython 規定的數字）----
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_READ = const(0x0002)
_WRITE_NO_RESPONSE = const(0x0004)
_WRITE = const(0x0008)
_NOTIFY = const(0x0010)

# ---- 服務 1：Nordic LED Button Service（nRF Blinky 認得這組 UUID）----
LBS_UUID = bluetooth.UUID("00001523-1212-EFDE-1523-785FEABCD123")
LBS_BUTTON = (bluetooth.UUID("00001524-1212-EFDE-1523-785FEABCD123"), _READ | _NOTIFY)
LBS_LED = (bluetooth.UUID("00001525-1212-EFDE-1523-785FEABCD123"), _READ | _WRITE | _WRITE_NO_RESPONSE)

# ---- 服務 2：Nordic UART Service（傳文字）----
NUS_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
NUS_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), _READ | _NOTIFY)              # 板子 → 手機
NUS_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), _WRITE | _WRITE_NO_RESPONSE)  # 手機 → 板子

SERVICES = (
    (LBS_UUID, (LBS_BUTTON, LBS_LED)),
    (NUS_UUID, (NUS_TX, NUS_RX)),
)

events = []          # 藍牙事件先排隊，主迴圈再慢慢處理
connections = set()


def show(line1, line2="", line3="", line4=""):
    oled.fill(0)
    for i, text in enumerate((line1, line2, line3, line4)):
        if text:
            draw_text(oled, 0, i * 16, text)
    oled.show()


def set_rgb(r, g, b):
    r, g, b = [max(0, min(255, int(v))) for v in (r, g, b)]
    for i in range(NUM_PIXELS):
        np[i] = (r, g, b)
    np.write()


def beep(freq=880, ms=150):
    buzzer.freq(freq)
    buzzer.duty(512)
    time.sleep_ms(ms)
    buzzer.duty(0)


def adv_payload(name=None, services=()):
    """組廣播封包：每一段＝[長度][種類][內容]，整包最多 31 個位元組"""
    payload = bytearray()

    def add(kind, value):
        payload.extend(struct.pack("BB", len(value) + 1, kind) + value)

    add(0x01, b"\x06")                    # 旗標：一般可被發現、不支援傳統藍牙
    for uuid in services:
        add(0x07, bytes(uuid))            # 128 位元服務 UUID
    if name:
        add(0x09, name.encode())          # 完整裝置名稱
    return payload


ble = bluetooth.BLE()
ble.active(True)
ble.config(gap_name=NAME)
((h_button, h_led), (h_tx, h_rx)) = ble.gatts_register_services(SERVICES)
ble.gatts_set_buffer(h_rx, 128)          # 文字指令最多 128 個位元組
ble.gatts_write(h_button, b"\x00")
ble.gatts_write(h_led, b"\x00")

# 廣播封包放「服務 UUID」（nRF Blinky 靠它找到板子），名字放在掃描回應裡（31 位元組放不下兩樣）
ADV = adv_payload(services=(LBS_UUID,))
RESP = adv_payload(name=NAME)


def advertise():
    ble.gap_advertise(100000, adv_data=ADV, resp_data=RESP)   # 每 0.1 秒（100000 微秒）喊一次「我在這裡」


def on_ble(event, data):
    # 這個函式由藍牙系統呼叫：只記下事件，不在這裡做慢的事
    if event == _IRQ_CENTRAL_CONNECT:
        conn_handle, _, _ = data
        connections.add(conn_handle)
        events.append(("connect", None))
    elif event == _IRQ_CENTRAL_DISCONNECT:
        conn_handle, _, _ = data
        connections.discard(conn_handle)
        events.append(("disconnect", None))
        advertise()                       # 斷線後重新廣播，手機才找得到
    elif event == _IRQ_GATTS_WRITE:
        conn_handle, value_handle = data
        events.append((value_handle, bytes(ble.gatts_read(value_handle))))


ble.irq(on_ble)


def reply(text):
    """用 UART 服務回一行字給手機（手機要先訂閱通知才收得到）"""
    for c in connections:
        try:
            ble.gatts_notify(c, h_tx, (text + "\n").encode()[:100])
        except OSError:
            pass


def run_command(text):
    """文字指令：red on / yellow off / green on / rgb 255 0 0 / beep / off / temp
    第三顆燈在板子上是綠色（程式裡叫 led_blue），green、blue 兩個字都收。"""
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
    elif cmd == "temp":
        try:
            dht_sensor.measure()
            reply("temp {} C, hum {} %".format(dht_sensor.temperature(), dht_sensor.humidity()))
        except OSError:
            reply("DHT11 read failed")
    else:
        reply("? try: red on / green on / rgb 255 0 0 / beep / off / temp")
    print("手機說：", text.strip())


print("=== 第 11 課：藍牙遙控 ===")
print("手機 App 掃描這個名字：", NAME)
advertise()
show("BLE 遙控", NAME, "等手機連線")
beep(1046, 80)

last_button = 1
try:
    while True:
        # 1) 處理手機送來的事件
        while events:
            kind, value = events.pop(0)
            if kind == "connect":
                show("BLE 遙控", NAME, "手機已連線")
                beep(1318, 60)
            elif kind == "disconnect":
                show("BLE 遙控", NAME, "等手機連線")
            elif kind == h_led:                      # nRF Blinky 按開關
                on = len(value) > 0 and value[0] != 0
                led_red.value(1 if on else 0)
                show("BLE 遙控", NAME, "紅燈 開" if on else "紅燈 關")
                print("手機說：紅燈", "開" if on else "關")
            elif kind == h_rx:                       # 文字指令
                try:
                    run_command(value.decode())
                except Exception as e:               # 打錯字（例如 rgb a b c）不要讓整支程式停掉
                    print("指令看不懂：", e)
                    reply("? try: red on / green on / rgb 255 0 0 / beep / off / temp")
        # 2) 板子的 A 鍵 → 通知手機（按下＝1、放開＝0）
        now = btn_a.value()
        if now != last_button:
            last_button = now
            pressed = b"\x01" if now == 0 else b"\x00"
            ble.gatts_write(h_button, pressed)
            for c in connections:
                try:
                    ble.gatts_notify(c, h_button, pressed)
                except OSError:
                    pass
        time.sleep_ms(20)
finally:
    ble.active(False)
    led_red.value(0)
    set_rgb(0, 0, 0)
