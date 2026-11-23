# 給 Codex 的規則（創客入門 ESP32 資料夾）

你在幫東華大學通識課「創客入門」的學生改 ESP32 程式。學生多數不是資訊科系，他們用自然語言請你改程式，再自己上傳到板子、親眼驗收。

## 回答方式

- 一律用繁體中文、台灣用語回答；程式碼、檔名、指令保留原文。
- 每次只改學生要求的那一件事。改之前先把要改的檔案複製到 `maker-backup/`（資料夾不存在就建立）。**備份前先把 `WIFI_PASSWORD`、`TG_TOKEN`、`TG_CHAT_ID`、`MOENV_KEY` 這類密碼欄在備份裡改成空字串**——教室電腦是共用的，備份會留給下一個人看到。
- 改完列出改了哪個檔案、哪幾行，用一兩句話說明為什麼。
- **不要自己上傳到板子、不要燒錄韌體、不要安裝驅動**。上傳由學生用 VS Code 任務「ESP32: Upload lesson (pick one)」或「ESP32: Upload all」自己按。
- 沒有在板子上跑過的東西，要寫「還沒在板子上測過」，不可以說「完成了」或「可以動了」。

## 板子（Circus ESP32 EZ Start Kit+，MicroPython v1.29.0）

所有元件已經在 `esp32/lib/ezkit.py` 設定好，範例都用 `from lib.ezkit import *`。**不要改腳位**，也不要對 ezkit 已經用到的腳位再建立一次 `Pin(...)` 或 `PWM(...)`（例如再寫 `Pin(16, Pin.OUT)`，會跟 ezkit 的 PWM 互搶，燈就不聽話）。

| 元件 | GPIO | ezkit 裡的名字 |
|---|---|---|
| 紅／黃／綠 LED | 16／12／13 | `led_red`、`led_yellow`、`led_blue`（第三顆板子上是綠色，名字沿用 `led_blue`）：`on()`、`off()`、`value(1)`；調亮度用 `led_red_pwm.duty(0~1023)`。同一顆燈在一支程式裡只選一種用法（開關或調亮度），混用時 `value()` 讀回來的狀態會不準 |
| WS2812 彩色燈 ×3 | 26 | `np`（`np[i] = (r, g, b)` 後要 `np.write()`） |
| 被動蜂鳴器 | 14 | `buzzer`（`freq()`、`duty()`；結束一定要 `duty(0)`） |
| 按鈕 A／B | 5／36 | `btn_a`、`btn_b`（按下讀到 0） |
| 光敏電阻／旋鈕 | 39／34 | `light_sensor`、`potentiometer`（`read()` 得 0–4095） |
| DHT11 溫濕度 | 15 | `dht_sensor`（先 `measure()` 再讀；兩次至少隔 2 秒，要包 `try/except OSError`） |
| 紅外線接收 | 33 | `ir_pin` |
| 繼電器 | 25 | `relay`（只接低電壓，不接家用電） |
| OLED 128×64 | SDA 21、SCL 22 | `oled`；中文用 `draw_text(oled, x, y, 文字)` 或 `oled_zh(...)` |

- GPIO 34、35、36、39 只能當輸入，而且沒有內建上拉電阻，不要寫 `Pin.PULL_UP`。
- 空著可以接外部零件的腳（擴充板上印的標號和 GPIO 編號不一樣）：板面 IO9＝GPIO 32、IO10＝GPIO 17、IO12＝GPIO 4、IO14＝GPIO 27（輸入輸出都可）、IO8＝GPIO 35（只能輸入）。程式裡寫的是 GPIO 編號。

## 常見的坑

- **OLED 中文**只認得 `esp32/lib/zhfont.py` 裡有的字，其他中文字會變成方塊。要新增字：把字加進 `tools/gen_font.py` 的 `CHARS`，執行 VS Code 任務「ESP32: Generate font」，它會在資料夾最上層產生 `zhfont.py`，再把它複製到 `esp32/lib/zhfont.py`。
- **不要用很長的 `time.sleep()`**：迴圈裡要同時看按鈕、網路或藍牙時，用 `time.ticks_ms()` 判斷時間到了沒，`sleep` 最多幾十毫秒。
- **WiFi**：這塊 ESP32 只能連 2.4 GHz；要網頁登入或帳號密碼的校園 WiFi 連不上。板子自己當基地台時，網址是 `192.168.4.1`。WiFi 名稱要用 `machine.unique_id()` 做出每塊板子不一樣的名字（參考 `d10_wifi_web.py`）。
- **藍牙**：用內建的 `bluetooth` 模組（參考 `d11_ble_remote.py`），板子上沒有裝 `aioble`。不要改既有的 UUID，手機 App 靠它們認板子。
- **網頁伺服器**一次只處理一個請求；處理時間長的動作（例如燈效跑好幾秒）要讓學生知道網頁會等。
- **紅外線遙控器**一律用 `esp32/lib/irkeys.py`（`ir.poll()`、`ir.held()`、`ir.name()`、`load_keys()`），不要自己手刻訊號時序或讀 `ir_pin` 算時間。有用紅外線的程式，OLED 更新寫 `ir.show(oled)`、不要寫 `oled.show()`（整個畫面一次送會卡住二三十毫秒，遙控器的訊號就收壞了）。記好的鍵存在板子上的 `ir_keys.json`，不要刪它。
- **第 15 課的一行一筆格式**（`{"knob":…,"light":…,"a":…,"b":…,"key":…}`）不要改欄位名稱，`web/game.html` 靠這些名字讀；要加資料就加新欄位。
- **`web/game.html` 標著「連線這一段：這段不要請 AI 改」的那段不要改**；要改遊戲、配色、接到球時叫板子做什麼，改它下面的段落。
- **序列埠一次只能一個程式用**：VS Code 的「ESP32: Serial monitor」開著時網頁連不上；網頁連著時上傳會失敗。請學生先關掉另一個。
- 板子會把上傳的課程存成 `main.py`，開機自動執行。程式要能被 Ctrl+C 中斷（不要寫成卡死在 C 函式裡、沒有逾時的等待）。

## 不能做的事

- 不要把 WiFi 密碼、熱點密碼、金鑰、token 寫進要 commit 或分享的檔案；學生需要填的時候提醒他們做完改回空白。
- 不要讀取或改動 `maker-esp32` 資料夾以外的檔案。
- 不要改 `tools/`、`.vscode/`、`setup-vscode-codex.*`，除非學生明確要求。
