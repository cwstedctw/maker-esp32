# ============================================
# 第 14 課：OLED 接球遊戲（遙控器、按鈕、旋鈕都能玩）
# ============================================
# 學習目標：
#   - 做一個會動的小遊戲：球從上面掉下來，用底下的板子接住
#   - 三種控制可以同時用：遙控器左右鍵、板子 B（往左）A（往右）、轉旋鈕
#   - 了解「遊戲迴圈」：讀輸入 → 更新位置 → 畫畫面，一秒重複二十幾次
#
# 怎麼玩：
#   - 遙控器左右鍵要先在第 13 課記好（板子上要有 ir_keys.json）；沒記過也能用 A、B、旋鈕玩
#   - 接到球加 1 分、嗶一聲；漏掉 3 顆遊戲結束
#   - 遊戲結束畫面：按 A、按 B 或遙控器確定鍵，重來一局
#
# 你會學到：
#   - 用 time.ticks_ms() 算每一圈經過多久，讓球速不受畫面快慢影響
#   - 旋鈕跟按鍵怎麼一起用：旋鈕「有轉動」才接管位置，免得跟按鍵互搶
#
# 停止：在 Serial monitor 按 Ctrl+C
# ============================================

from lib.ezkit import *
from lib.irkeys import IRKeys
import random

# ---- 你可以改的數字 ----
BALL_SPEED = 28           # 球往下掉的速度（每秒幾個點；螢幕高 64 點）
PADDLE_W = 26             # 底下板子的寬度（點；螢幕寬 128 點）
PADDLE_SPEED = 90         # 用按鍵移動板子的速度（每秒幾個點）
LIVES = 3                 # 幾條命（漏掉幾顆就結束）
BALL_SIZE = 4             # 球的大小（點）
KNOB_THRESHOLD = 150      # 旋鈕轉超過多少（0～4095 裡的多少）才接管板子位置
FRAME_MS = 40             # 每一個畫面至少隔幾毫秒（40＝每秒最多 25 個畫面）

# ---- 畫面位置（一般不用改）----
W = 128
H = 64
TOP = 10                  # 最上面 10 點放分數和命
PADDLE_Y = H - 4          # 板子的 y 位置
PADDLE_H = 3

ir = IRKeys(ir_pin)       # 開始聽遙控器（會自動讀第 13 課存的 ir_keys.json）

beep_off_at = None


def beep(freq, ms):
    """開始嗶，時間到了主迴圈會關掉（不用 sleep 卡住遊戲）"""
    global beep_off_at
    buzzer.freq(freq)
    buzzer.duty(512)
    beep_off_at = time.ticks_add(time.ticks_ms(), ms)


def read_knob():
    """讀旋鈕兩次取平均，數字比較不會亂跳"""
    return (potentiometer.read() + potentiometer.read()) // 2


def knob_to_x(v):
    """旋鈕 0～4095 → 板子左邊的 x（0～128 減板子寬）"""
    # 這塊板子的旋鈕往右轉（順時針）讀數變小，所以倒過來算，往右轉板子才會往右
    return (4095 - v) * (W - PADDLE_W) // 4095


def new_ball():
    """新的一顆球：從最上面隨便一個位置開始掉"""
    return random.randint(0, W - BALL_SIZE), float(TOP)


def draw_start():
    oled.fill(0)
    draw_text(oled, 48, 0, "接球")
    draw_text(oled, 0, 16, "左右鍵 或 A B")
    draw_text(oled, 0, 32, "也可以轉旋鈕")
    draw_text(oled, 0, 48, "A B 確定開始" if ir.keys else "按 A 或 B 開始")
    ir.show(oled)


def draw_over(score):
    oled.fill(0)
    draw_text(oled, 0, 0, "沒接到{}顆".format(LIVES))
    draw_text(oled, 0, 16, "分數 {}".format(score))
    draw_text(oled, 0, 32, "按 A 或 B")
    draw_text(oled, 0, 48, "或確定 重來" if ir.keys else "可以重來")
    ir.show(oled)


def draw_game(px, bx, by, score, lives):
    oled.fill(0)
    oled.text(str(score), 0, 0, 1)                   # 左上：分數（英數字比較省時間）
    for i in range(lives):                           # 右上：剩幾條命，一條一個小方塊
        oled.fill_rect(W - 8 - i * 8, 1, 6, 6, 1)
    oled.hline(0, TOP - 2, W, 1)
    oled.fill_rect(int(bx), int(by), BALL_SIZE, BALL_SIZE, 1)
    oled.fill_rect(int(px), PADDLE_Y, PADDLE_W, PADDLE_H, 1)
    ir.show(oled)                                    # 用 ir.show：送畫面時會避開紅外線訊號


def wait_start():
    """開始畫面：等玩家按 A、B 或遙控器確定鍵（放開後才開始，免得一開始板子就跑掉）"""
    draw_start()
    while True:
        code = ir.poll()
        if ir.name(code) == "ok" or btn_a.value() == 0 or btn_b.value() == 0:
            break
        time.sleep_ms(20)
    while btn_a.value() == 0 or btn_b.value() == 0:   # 等手放開
        time.sleep_ms(10)


def wait_restart(score):
    """結束畫面：先停 1 秒（免得最後一刻還按著 A、B 就直接重來），再等 A、B 或確定鍵"""
    draw_over(score)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 1000:
        ir.poll()                                    # 這一秒按的鍵丟掉
        tick_beep()
        time.sleep_ms(20)
    while btn_a.value() == 0 or btn_b.value() == 0:   # 還按著就等放開
        time.sleep_ms(10)
    while True:
        code = ir.poll()
        if ir.name(code) == "ok" or btn_a.value() == 0 or btn_b.value() == 0:
            break
        time.sleep_ms(20)
    while btn_a.value() == 0 or btn_b.value() == 0:
        time.sleep_ms(10)


def tick_beep():
    global beep_off_at
    if beep_off_at is not None and time.ticks_diff(time.ticks_ms(), beep_off_at) >= 0:
        buzzer.duty(0)
        beep_off_at = None


def play():
    """玩一局，回傳分數"""
    score = 0
    lives = LIVES
    px = float((W - PADDLE_W) // 2)                  # 板子位置（左邊的 x）
    bx, by = new_ball()
    knob_ref = read_knob()                           # 旋鈕「上一次用來決定位置」的讀數
    knob_on = False                                  # 現在是不是旋鈕在控制
    last = time.ticks_ms()
    frames = 0
    fps_t = last

    while lives > 0:
        now = time.ticks_ms()
        dt = time.ticks_diff(now, last) / 1000       # 這一圈經過幾秒
        last = now
        if dt > 0.2:
            dt = 0.2                                 # 卡住太久時不要讓球一下子跳太遠

        # 1) 讀輸入：遙控器、按鈕、旋鈕
        ir.poll()                                    # 遊戲中只看「按著哪個鍵」，剛按下的事件丟掉
        key = ir.name(ir.held())
        go_left = key == "left" or btn_b.value() == 0     # 板子上 B 鍵在左邊
        go_right = key == "right" or btn_a.value() == 0   # A 鍵在右邊

        k = read_knob()
        if go_left or go_right:
            knob_on = False                          # 按鍵一動，旋鈕就讓位
            knob_ref = k
            if go_left:
                px -= PADDLE_SPEED * dt
            if go_right:
                px += PADDLE_SPEED * dt
        elif abs(k - knob_ref) > KNOB_THRESHOLD:
            knob_on = True                           # 旋鈕真的轉了，才接管
        if knob_on:
            px = knob_to_x(k)
            knob_ref = k
        px = max(0, min(W - PADDLE_W, px))

        # 2) 更新球的位置
        by += BALL_SPEED * dt
        if by + BALL_SIZE >= PADDLE_Y:
            if px - BALL_SIZE < bx < px + PADDLE_W:
                score += 1                           # 接到了
                beep(1568, 40)
                print("接到！分數", score)
                bx, by = new_ball()
            elif by > H:
                lives -= 1                           # 漏掉了
                beep(196, 250)
                print("漏掉了，剩", lives, "條命")
                if lives == 0:
                    break                            # 沒命了：直接到結束畫面
                bx, by = new_ball()

        # 3) 畫畫面、關嗶聲
        draw_game(px, bx, by, score, lives)
        tick_beep()

        # 每 5 秒印一次每秒畫面數（看遊戲順不順）
        frames += 1
        if time.ticks_diff(now, fps_t) >= 5000:
            print("每秒畫面數：", frames * 1000 // time.ticks_diff(now, fps_t))
            frames = 0
            fps_t = now

        # 4) 太快就等一下，讓每個畫面至少隔 FRAME_MS
        spent = time.ticks_diff(time.ticks_ms(), now)
        if spent < FRAME_MS:
            time.sleep_ms(FRAME_MS - spent)
    return score


print("=== 第 14 課：OLED 接球遊戲 ===")
if ir.keys:
    print("讀到記好的遙控器鍵：", ir.keys)
else:
    print("沒有 ir_keys.json：遙控器先不能玩，用 A、B、旋鈕（要用遙控器請先跑第 13 課記鍵）")

try:
    wait_start()
    while True:
        s = play()
        print("遊戲結束，分數", s)
        wait_restart(s)
finally:
    buzzer.duty(0)
    ir.stop()
