# ============================================
# 第 12 課：上網抓空氣品質（AQI）→ OLED → Telegram
# ============================================
# 學習目標：
#   - 讓 ESP32 連上「有網際網路」的 WiFi（手機熱點、家裡的 WiFi）
#   - 用 GET 請求跟網路上的服務要資料，拿回一段 JSON，挑出要的數字
#   - 把空氣品質顯示在 OLED，再用 GET 請求把它送到你的 Telegram
#
# 資料從哪來（看 MOENV_KEY 有沒有填）：
#   - 沒填：open-meteo（免金鑰，歐洲大氣模式「推估」的 AQI，跟台灣測站算法不同）
#   - 有填：環境部 aqx_p_432（台灣測站「實測」，每小時更新一次；金鑰要自己到環境部平臺註冊）
#
# 按鈕：A＝馬上把現在的數字送到 Telegram　B＝馬上重新抓一次
# 停止：在 Serial monitor 按 Ctrl+C
#
# ⚠️ 這個檔填了密碼和 token 之後，不要截圖、不要傳給別人。做完改回空白。
# ⚠️ ESP32 只認 2.4 GHz；學校要網頁登入的 WiFi 連不上（用手機熱點）。
# ============================================

from lib.ezkit import *
import network
import requests
import json
import machine
import gc

# ---- 1. 你的 WiFi（要能上網）----
WIFI_SSID = ""
WIFI_PASSWORD = ""

# ---- 2. 空氣品質資料 ----
MOENV_KEY = ""            # 環境部 API 金鑰；空白＝改用 open-meteo
SITE = "花蓮"              # 環境部測站名稱（注意「臺」不是「台」，例如 臺東）
LAT, LON = 23.97694, 121.60444   # open-meteo 用的經緯度（花蓮市）
CHECK_MINUTES = 10         # 幾分鐘抓一次（測站一小時才更新，抓太勤也不會變）

# ---- 3. 送出去（都可以留空）----
TG_TOKEN = ""             # Telegram 機器人的 token（W7 跟 BotFather 要的那串）
TG_CHAT_ID = ""           # 你的 chat id
ALERT_AQI = 100           # AQI 從低於這個數字變成超過時，自動送一則警告
REPORT_URL = ""           # 選做：把資料用 GET 送到這個網址（例如老師的伺服器）

# 老師示範用：板子上如果有 my_secrets.py，就用裡面的設定（投影時不會露出密碼）
try:
    from my_secrets import *
except ImportError:
    pass

BOARD_ID = "".join("{:02X}".format(b) for b in machine.unique_id()[-2:])


def show(line1, line2="", line3="", line4=""):
    oled.fill(0)
    for i, text in enumerate((line1, line2, line3, line4)):
        if text:
            draw_text(oled, 0, i * 16, text)
    oled.show()


def quote(text):
    """把中文、空白這些字變成網址可以放的樣子：花 → %E8%8A%B1"""
    out = ""
    for b in str(text).encode("utf-8"):
        c = chr(b)
        if b < 128 and (c.isalpha() or c.isdigit() or c in "-_.~"):
            out += c
        else:
            out += "%{:02X}".format(b)
    return out


def level(aqi):
    """AQI 分級（環境部 2025 年起的門檻；open-meteo 的美國 AQI 分級邊界相同）"""
    if aqi <= 50:
        return "良好"
    if aqi <= 100:
        return "普通"
    if aqi <= 150:
        return "對敏感族群不健康"
    if aqi <= 200:
        return "對所有族群不健康"
    if aqi <= 300:
        return "非常不健康"
    return "危害"


# ============================================
# 第一步：連上能上網的 WiFi
# ============================================

def connect_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if sta.isconnected():
        return True
    if not WIFI_SSID:
        show("還沒填 WiFi", "打開程式", "填 WIFI_SSID")
        print("請在程式最上面填 WIFI_SSID 和 WIFI_PASSWORD")
        return False
    show("連線中", WIFI_SSID[:16])
    print("連線到", WIFI_SSID, "...")
    sta.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(40):                     # 最多等 20 秒
        if sta.isconnected():
            print("連上了！板子的 IP：", sta.ifconfig()[0])
            return True
        time.sleep(0.5)
    show("連不上 WiFi", "看名稱密碼", "要 2.4 GHz")
    print("連不上", WIFI_SSID, "：名稱、密碼對嗎？是 2.4 GHz 嗎？")
    sta.active(False)
    return False


# ============================================
# 第二步：用 GET 請求要空氣品質資料
# ============================================

def get_json(url):
    """送出 GET 請求，回傳 (狀態碼, 內容文字)"""
    r = requests.get(url, timeout=15)
    try:
        return r.status_code, r.text
    finally:
        r.close()                           # 用完一定要關，不然板子的記憶體會被佔住


def fetch_moenv():
    url = ("https://data.moenv.gov.tw/api/v2/aqx_p_432?api_key=" + MOENV_KEY
           + "&format=JSON&filters=sitename,EQ," + quote(SITE))
    code, text = get_json(url)
    if not text.startswith("["):            # 金鑰錯、用完時，回的是一行中文、不是 JSON
        raise ValueError("環境部說：" + text[:60])
    rows = json.loads(text)
    if not rows:
        raise ValueError("找不到測站：" + SITE)
    row = rows[0]
    return {
        "source": "環境部 " + row["sitename"] + "（實測）",
        "aqi": int(row["aqi"]),             # 環境部的數字都是「字串」，要轉成整數才能比大小
        "pm25": row["pm2.5"],
        "time": row["publishtime"],
    }


def fetch_openmeteo():
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude={}&longitude={}"
           "&current=us_aqi,pm2_5&timezone=Asia%2FTaipei").format(LAT, LON)
    code, text = get_json(url)
    if code != 200:
        raise ValueError("open-meteo 回 " + str(code))
    now = json.loads(text)["current"]
    return {
        "source": "open-meteo（推估）",
        "aqi": int(now["us_aqi"]),
        "pm25": now["pm2_5"],
        "time": now["time"].replace("T", " "),
    }


def fetch():
    gc.collect()
    data = fetch_moenv() if MOENV_KEY else fetch_openmeteo()
    data["level"] = level(data["aqi"])
    print("抓到：", data["source"], "AQI", data["aqi"], data["level"], "PM2.5", data["pm25"], data["time"])
    return data


def show_data(d):
    where = SITE if MOENV_KEY else "推估"
    show("空氣 " + where, "AQI " + str(d["aqi"]), d["level"], "PM2.5 " + str(d["pm25"]))


# ============================================
# 第三步：把資料送出去（GET 請求：資料放在網址後面）
# ============================================

def send_telegram(text):
    if not (TG_TOKEN and TG_CHAT_ID):
        print("沒填 TG_TOKEN／TG_CHAT_ID：只顯示、不送 Telegram")
        return False
    # 網址＝ https://api.telegram.org/bot<token>/sendMessage ？chat_id=…&text=…
    url = ("https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage?chat_id="
           + quote(TG_CHAT_ID) + "&text=" + quote(text))
    try:
        code, body = get_json(url)
        ok = '"ok":true' in body
        print("Telegram 回：", code, "ok" if ok else body[:80])   # 只印結果，不印網址（裡面有 token）
        return ok
    except Exception as e:
        print("Telegram 送不出去：", e)
        return False


def send_report(d):
    if not REPORT_URL:
        return
    url = (REPORT_URL + "?board=" + BOARD_ID + "&aqi=" + str(d["aqi"])
           + "&pm25=" + quote(d["pm25"]) + "&time=" + quote(d["time"]))
    try:
        code, body = get_json(url)
        print("送到 REPORT_URL：", code)
    except Exception as e:
        print("REPORT_URL 送不出去：", e)


def message(d, alert=False):
    head = "⚠️ 空氣變差了\n" if alert else ""
    return "{}{}\nAQI {}（{}）\nPM2.5 {} μg/m³\n{}\n板子 {}".format(
        head, d["source"], d["aqi"], d["level"], d["pm25"], d["time"], BOARD_ID)


# ============================================
# 主程式
# ============================================

print("=== 第 12 課：上網抓空氣品質 ===")
show("空氣品質", "第 12 課")
time.sleep(1)

data = None
last_aqi = None
next_fetch = time.ticks_ms()                # 一開始就抓
last_a = last_b = 1

try:
    while True:
        now = time.ticks_ms()
        if time.ticks_diff(now, next_fetch) >= 0:
            if connect_wifi():
                try:
                    show("抓資料中", "請稍等")
                    data = fetch()
                    show_data(data)
                    if last_aqi is None:
                        send_telegram(message(data))          # 開機第一次抓到：送一則
                    elif last_aqi <= ALERT_AQI < data["aqi"]:
                        send_telegram(message(data, alert=True))   # 從普通變差：送警告
                        buzzer.freq(880); buzzer.duty(512); time.sleep_ms(300); buzzer.duty(0)
                    send_report(data)
                    last_aqi = data["aqi"]
                    next_fetch = time.ticks_add(now, CHECK_MINUTES * 60000)
                except Exception as e:
                    print("抓資料失敗：", e)
                    show("抓資料失敗", "1 分鐘後", "再試一次")
                    next_fetch = time.ticks_add(now, 60000)
            else:
                next_fetch = time.ticks_add(now, 60000)
        a, b = btn_a.value(), btn_b.value()
        if a == 0 and last_a == 1 and data:
            show("送 Telegram", "請稍等")
            show("已送出" if send_telegram(message(data)) else "沒送出", "看序列埠")
            time.sleep(1)
            show_data(data)
        if b == 0 and last_b == 1:
            next_fetch = time.ticks_ms()        # 馬上重新抓
        last_a, last_b = a, b
        time.sleep_ms(50)
finally:
    buzzer.duty(0)
