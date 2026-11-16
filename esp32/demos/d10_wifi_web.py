# ============================================
# 第 10 課：WiFi 網頁遙控（手機開網頁控制板子）
# ============================================
# 學習目標：
#   - 讓 ESP32 用 WiFi 開一個「網頁伺服器」
#   - 用手機瀏覽器打開板子的網址，按按鈕控制 LED、RGB 燈、蜂鳴器
#   - 在網頁上看到板子即時量到的溫度、濕度、光線、旋鈕
#
# 兩種連法（看下面 WIFI_SSID）：
#   1. 板子自己當基地台（預設，不用任何網路）：
#      OLED 會顯示 WiFi 名稱和密碼 → 手機連上 → 瀏覽器打 192.168.4.1
#   2. 板子去連現有的 WiFi（手機熱點、老師的路由器）：
#      把 WIFI_SSID、WIFI_PASSWORD 填好 → OLED 會顯示板子拿到的 IP
#      → 跟板子在同一個 WiFi 的手機或電腦打 http://那個IP
#      ⚠️ 只認 2.4 GHz；要網頁登入或帳號密碼的校園 WiFi 連不上
#
# 你會學到：
#   - 網址（IP）、網頁伺服器、HTTP 請求是什麼
#   - 網頁上的按鈕怎麼變成板子上的動作
#
# 停止：在 Serial monitor 按 Ctrl+C
# ============================================

from lib.ezkit import *
import network
import socket
import json
import machine

# ---- 想連現有的 WiFi 就填這兩行；留空＝板子自己當基地台 ----
WIFI_SSID = ""
WIFI_PASSWORD = ""

# 每塊板子的編號：取晶片 MAC 位址最後兩個位元組，例如 "A1B2"
BOARD_ID = "".join("{:02X}".format(b) for b in machine.unique_id()[-2:])
AP_SSID = "maker-" + BOARD_ID          # 基地台模式的 WiFi 名稱
AP_PASSWORD = "maker" + BOARD_ID       # 基地台模式的密碼（WPA2 至少 8 個字）

# 板子的狀態（網頁會讀這些）
state = {
    "red": False, "yellow": False, "blue": False,
    "rgb": [0, 0, 0],
    "temp": None, "hum": None,
    "light": 0, "knob": 0,
    "last": "",
    "requests": 0,
}
LEDS = {"red": led_red, "yellow": led_yellow, "blue": led_blue}
NAMES_ZH = {"red": "紅燈", "yellow": "黃燈", "blue": "藍燈"}


def show(line1, line2="", line3="", line4=""):
    """OLED 四行：中文用 draw_text（只認得字型檔裡的字），英數字用內建字型"""
    oled.fill(0)
    for i, text in enumerate((line1, line2, line3, line4)):
        if text:
            draw_text(oled, 0, i * 16, text)
    oled.show()


def all_off():
    for name, pin in LEDS.items():
        pin.value(0)
        state[name] = False
    set_rgb(0, 0, 0)


def set_rgb(r, g, b):
    r, g, b = [max(0, min(255, int(v))) for v in (r, g, b)]
    for i in range(NUM_PIXELS):
        np[i] = (r, g, b)
    np.write()
    state["rgb"] = [r, g, b]


def beep(freq=880, ms=150):
    buzzer.freq(freq)
    buzzer.duty(512)
    time.sleep_ms(ms)
    buzzer.duty(0)


# ============================================
# 第一步：連上 WiFi（或自己當基地台）
# ============================================

def get_ip(wlan):
    try:
        return wlan.ipconfig("addr4")[0]   # MicroPython 1.24 以後的寫法
    except Exception:
        return wlan.ifconfig()[0]          # 舊寫法


def connect_wifi():
    """回傳 (模式, WiFi 名稱, 網址)"""
    if WIFI_SSID:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        show("連線中", WIFI_SSID[:16])
        print("連線到", WIFI_SSID, "...")
        sta.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(40):                 # 最多等 20 秒
            if sta.isconnected():
                ip = get_ip(sta)
                print("連上了！板子的 IP：", ip)
                return "STA", WIFI_SSID, ip
            time.sleep(0.5)
        print("連不上", WIFI_SSID, "→ 改成板子自己當基地台")
        sta.disconnect()
        sta.active(False)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    # 頻道錯開（1、6、11），全班 30 塊板子同時開比較不會互相干擾
    channel = (1, 6, 11)[machine.unique_id()[-1] % 3]
    ap.config(essid=AP_SSID, password=AP_PASSWORD,
              authmode=getattr(network, "AUTH_WPA2_PSK", 3), channel=channel)
    while not ap.active():
        time.sleep(0.1)
    ip = get_ip(ap)
    print("基地台模式  WiFi 名稱：", AP_SSID, " 密碼：", AP_PASSWORD, " 網址：http://" + ip)
    return "AP", AP_SSID, ip


# ============================================
# 第二步：網頁（手機打開看到的畫面）
# ============================================
# 網頁本身是一大段 HTML 文字，存在板子上，手機來要的時候整段送出去。
# 按鈕被按下時，網頁用 fetch() 去要 /api/... 這種網址，板子收到就動作。

PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 遙控器</title>
<style>
body{font-family:system-ui,"Microsoft JhengHei",sans-serif;margin:0;padding:16px;background:#f4f1ea;color:#222}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#666;font-size:14px;margin-bottom:14px}
.card{background:#fff;border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px #0002}
.row{display:flex;gap:10px;flex-wrap:wrap}
button{flex:1;min-width:90px;font-size:18px;padding:14px 8px;border:0;border-radius:12px;background:#ddd;color:#222}
button.on{color:#fff}
#red.on{background:#d33}#yellow.on{background:#e8b400}#blue.on{background:#2a6fdb}
.sensors{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:16px}
.sensors b{font-size:22px;display:block}
input[type=color]{width:100%;height:48px;border:0;background:none}
#msg{font-size:14px;color:#666;min-height:20px}
</style></head><body>
<h1>ESP32 遙控器</h1>
<div class="sub">板子編號 __ID__</div>
<div class="card"><div class="row">
<button id="red" onclick="led('red')">紅燈</button>
<button id="yellow" onclick="led('yellow')">黃燈</button>
<button id="blue" onclick="led('blue')">藍燈</button>
</div></div>
<div class="card">RGB 彩色燈：選一個顏色
<input type="color" id="color" value="#000000" onchange="rgb(this.value)">
<div class="row"><button onclick="rgb('#000000')">彩色燈關</button><button onclick="call('/api/beep')">嗶一聲</button></div>
</div>
<div class="card sensors">
<div>溫度<b id="temp">--</b></div><div>濕度<b id="hum">--</b></div>
<div>光線<b id="light">--</b></div><div>旋鈕<b id="knob">--</b></div>
</div>
<div class="card"><div class="row"><button onclick="call('/api/off')">全部關掉</button></div></div>
<div id="msg"></div>
<script>
var S={};
function call(url){return fetch(url).then(function(r){return r.json()}).then(draw)
 .catch(function(){document.getElementById('msg').textContent='連不到板子：手機還連著板子的 WiFi 嗎？'})}
function led(n){call('/api/led?name='+n+'&on='+(S[n]?0:1))}
function rgb(hex){var v=parseInt(hex.slice(1),16);call('/api/rgb?r='+(v>>16)+'&g='+((v>>8)&255)+'&b='+(v&255))}
function draw(s){S=s;['red','yellow','blue'].forEach(function(n){document.getElementById(n).className=s[n]?'on':''});
 document.getElementById('temp').textContent=s.temp==null?'--':s.temp+' °C';
 document.getElementById('hum').textContent=s.hum==null?'--':s.hum+' %';
 document.getElementById('light').textContent=s.light;
 document.getElementById('knob').textContent=s.knob;
 document.getElementById('msg').textContent='已更新 '+new Date().toLocaleTimeString()}
call('/api/status');setInterval(function(){call('/api/status')},2000);
</script></body></html>"""

PAGE_BYTES = PAGE.replace("__ID__", BOARD_ID).encode()


# ============================================
# 第三步：處理手機送來的請求
# ============================================

def parse_query(path):
    """'/api/led?name=red&on=1' → ('/api/led', {'name': 'red', 'on': '1'})"""
    if "?" not in path:
        return path, {}
    route, qs = path.split("?", 1)
    args = {}
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            args[k] = v
    return route, args


def send(conn, body, ctype="application/json", status="200 OK"):
    if isinstance(body, str):
        body = body.encode()
    head = "HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".format(
        status, ctype, len(body))
    conn.sendall(head.encode())
    conn.sendall(body)


def status_json():
    return json.dumps(state)


def handle(conn):
    # 手機瀏覽器常會先多開一條「空連線」備用、什麼都不送；等 1.5 秒沒資料就放掉，免得卡住別人
    conn.settimeout(1.5)
    try:
        line = conn.readline()             # 第一行像 b"GET /api/led?name=red&on=1 HTTP/1.1"
        while True:                        # 其他標頭讀完丟掉，讀到空行為止
            h = conn.readline()
            if not h or h == b"\r\n":
                break
    except OSError:
        return
    parts = line.decode().split(" ")
    if len(parts) < 2:
        return
    route, args = parse_query(parts[1])
    state["requests"] += 1

    if route == "/":
        send(conn, PAGE_BYTES, "text/html; charset=utf-8")
        return
    if route == "/api/status":
        send(conn, status_json())
        return
    if route == "/api/led" and args.get("name") in LEDS:
        name = args["name"]
        on = args.get("on") == "1"
        LEDS[name].value(1 if on else 0)
        state[name] = on
        state["last"] = NAMES_ZH[name] + (" 開" if on else " 關")
    elif route == "/api/rgb":
        set_rgb(args.get("r", 0), args.get("g", 0), args.get("b", 0))
        state["last"] = "彩色燈"
    elif route == "/api/beep":
        beep()
        state["last"] = "蜂鳴器"
    elif route == "/api/off":
        all_off()
        state["last"] = "全部關"
    else:
        send(conn, '{"error":"not found"}', status="404 Not Found")
        return
    print("手機說：", state["last"])
    send(conn, status_json())
    show_main()


def read_sensors():
    state["light"] = light_sensor.read()
    state["knob"] = potentiometer.read()
    try:
        dht_sensor.measure()
        state["temp"] = dht_sensor.temperature()
        state["hum"] = dht_sensor.humidity()
    except OSError:
        pass                                # DHT11 偶爾讀失敗，留著上次的數字


# ============================================
# 主程式
# ============================================

print("=== 第 10 課：WiFi 網頁遙控 ===")
all_off()
mode, ssid, ip = connect_wifi()


def show_main():
    if mode == "AP":
        show("WiFi 遙控", ssid, "pw " + AP_PASSWORD, ip)
    else:
        show("WiFi 遙控", ssid[:16], "http://", ip)
    if state["last"]:
        oled.fill_rect(0, 48, 128, 16, 0)
        draw_text(oled, 0, 48, state["last"])
        oled.show()


show_main()
beep(1046, 80)

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(socket.getaddrinfo("0.0.0.0", 80)[0][-1])
server.listen(3)
server.settimeout(0.2)                      # 每 0.2 秒回來看一下感測器
print("網頁伺服器開好了：http://" + ip)

last_sensor = time.ticks_ms() - 5000
try:
    while True:
        if time.ticks_diff(time.ticks_ms(), last_sensor) > 2000:
            read_sensors()
            last_sensor = time.ticks_ms()
        try:
            conn, addr = server.accept()
        except OSError:
            continue                        # 這 0.2 秒沒人來，繼續等
        try:
            handle(conn)
        except Exception as e:
            print("處理請求時出錯：", e)
        finally:
            conn.close()
finally:
    server.close()
    all_off()
