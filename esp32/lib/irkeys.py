# ============================================
# irkeys.py — 紅外線遙控器認鍵模組（第 13、14、15 課共用）
# ============================================
# 用法（學生只要會這幾行）：
#
#   from lib.irkeys import IRKeys, load_keys, save_keys
#   ir = IRKeys(ir_pin)        # 開始聽遙控器
#   code = ir.poll()           # 剛按下的鍵碼（一個整數）；沒按就是 None
#   code = ir.held()           # 現在還按著的鍵碼；放開了就是 None
#   ir.name(code)              # 鍵碼 → 鍵名 "left"/"right"/"up"/"down"/"ok"；沒記過就是 ""
#   ir.show(oled)              # 更新 OLED 畫面（會避開正在收的紅外線訊號）
#
#   save_keys({"left": 123, ...})   # 把記好的鍵存成板子上的 ir_keys.json
#   load_keys()                     # 讀回來（沒有這個檔就回傳空的 {}）
#
# 原理（給好奇的人看）：
#   遙控器按一下，會送出一串「亮、暗、亮、暗……」的紅外線閃爍。
#   接收器收到亮的時候讀到 0、暗的時候讀到 1。
#   這個模組在每次 0/1 變化時記下時間（微秒），等訊號停下來，
#   再從「每一段有多長」算出這個鍵的號碼。
#   - 大部分套件遙控器用一種叫 NEC 的格式，可以直接讀出號碼。
#   - 不是 NEC 的遙控器，就把長短的樣子算成一個號碼（同一個鍵每次一樣）。
#
# ⚠️ 收訊號的時候，程式不能被卡住太久（OLED 一次整個畫面送出要二三十毫秒，
#    會讓訊號的時間記錯）。所以有用紅外線的程式，畫面更新請寫 ir.show(oled)，
#    不要寫 oled.show()；要 print 很長的字之前，先呼叫 ir.wait_quiet()。
# ============================================

import time
import machine
import json
from array import array

KEY_FILE = "ir_keys.json"           # 記鍵檔（存在板子上）
KEY_NAMES = ("left", "right", "up", "down", "ok")

GAP_US = 12000      # 超過 12 毫秒沒有新變化，就當作「這一串訊號結束了」
GLITCH_US = 150     # 比 0.15 毫秒還短的一段，當成雜訊合併掉
HOLD_MS = 200       # 超過 0.2 秒沒再收到同一個鍵，就當作放開了
MAX_EDGES = 200     # 一串訊號最多記幾個變化（預先準備好，收訊號時不用再配置記憶體）
QUIET_MAX_MS = 150  # 等訊號收完最多等多久（避免卡死）

# 解碼結果的種類
_NONE = 0       # 什麼都不是（太短、雜訊）
_FRAME = 1      # 一個完整的按鍵
_REPEAT = 2     # NEC 的「重複碼」：同一個鍵還按著
_BAD = 3        # 看起來像遙控器訊號，但壞掉了（不要當成新的鍵）


def load_keys(path=KEY_FILE):
    """讀板子上的記鍵檔，回傳 {"left": 鍵碼, ...}；沒有檔或檔壞掉就回傳 {}"""
    try:
        with open(path) as f:
            data = json.load(f)
        keys = {}
        for name in KEY_NAMES:
            if name in data:
                keys[name] = int(data[name])
        return keys
    except (OSError, ValueError, TypeError):
        return {}


def save_keys(keys, path=KEY_FILE):
    """把 {"left": 鍵碼, ...} 存成板子上的記鍵檔"""
    with open(path, "w") as f:
        json.dump(keys, f)


def code_text(code):
    """鍵碼 → 好讀的文字（十六進位），例如 00FF45"""
    if code is None:
        return "-"
    return "{:06X}".format(code)


class IRKeys:
    def __init__(self, pin, keys=None):
        self._pin = pin
        # 兩塊預先配置好的記錄區：一塊正在記，另一塊等主程式來解碼
        self._b0 = array("i", [0] * MAX_EDGES)
        self._b1 = array("i", [0] * MAX_EDGES)
        self._buf = self._b0        # 正在記的那塊
        self._n = 0                 # 正在記的那塊記了幾個
        self._last = 0              # 最後一次變化的時間（微秒）
        self._ready_buf = self._b1  # 記完、等解碼的那塊
        self._ready_n = 0           # 等解碼的那塊有幾個（0＝沒有）
        self._code = None           # 最近收到的鍵碼
        self._seen = 0              # 最近收到它的時間（毫秒）
        self._pressed = None        # 剛按下、還沒被 poll() 拿走的鍵碼
        self._pages = None
        self._pages_src = None
        self.last_kind = ""         # 最近一串訊號是什麼（"NEC"、"其他編碼"、"重複碼"…），除錯用
        self.keys = load_keys() if keys is None else dict(keys)
        pin.irq(handler=self._edge, trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING)

    # ---------- 收訊號（中斷裡跑，只做最少的事、不配置記憶體）----------
    def _edge(self, pin):
        t = time.ticks_us()
        n = self._n
        if n and time.ticks_diff(t, self._last) > GAP_US:
            # 上一串已經結束、主程式還沒來拿：交給等解碼區（已經有一串在等就丟掉這串）
            if self._ready_n == 0:
                self._ready_buf = self._buf
                self._buf = self._b1 if self._buf is self._b0 else self._b0
                self._ready_n = n
            n = 0
        if n < MAX_EDGES:
            self._buf[n] = t
            self._n = n + 1
        self._last = t

    def _service(self):
        """主程式這邊：把收完的訊號拿來解碼"""
        if self._n and self._ready_n == 0:
            st = machine.disable_irq()
            if self._n and self._ready_n == 0 and time.ticks_diff(time.ticks_us(), self._last) > GAP_US:
                self._ready_buf = self._buf
                self._buf = self._b1 if self._buf is self._b0 else self._b0
                self._ready_n = self._n
                self._n = 0
            machine.enable_irq(st)
        n = self._ready_n
        if n:
            buf = self._ready_buf
            # 訊號結束的時間換算成毫秒（不是現在的時間，免得主程式晚來拿就算錯）
            end_ms = time.ticks_add(time.ticks_ms(), -(time.ticks_diff(time.ticks_us(), buf[n - 1]) // 1000))
            kind, code = decode(buf, n)
            self._ready_n = 0
            self._handle(kind, code, end_ms)

    def _handle(self, kind, code, t):
        held = self._code is not None and time.ticks_diff(t, self._seen) < HOLD_MS
        if kind == _FRAME:
            self.last_kind = "常見編碼" if code < 0x1000000 else "其他編碼"
            if held and code == self._code:
                self._seen = t                  # 同一個鍵又送了一次整串：還按著，不算新的一下
            else:
                self._code = code
                self._seen = t
                self._pressed = code            # 新的一下
        elif kind == _REPEAT:
            self.last_kind = "重複碼"
            if self._code is not None and time.ticks_diff(t, self._seen) < HOLD_MS + 100:
                self._seen = t                  # 同一個鍵還按著
        elif kind == _BAD:
            self.last_kind = "訊號不完整"
            if held:
                self._seen = t                  # 按著的時候收到壞掉的一串，多半還是同一個鍵
        else:
            self.last_kind = "雜訊"

    # ---------- 給學生用的 ----------
    def poll(self):
        """回傳剛按下的鍵碼；沒有新按的就回傳 None"""
        self._service()
        code = self._pressed
        self._pressed = None
        return code

    def held(self):
        """回傳現在還按著的鍵碼；放開了就回傳 None"""
        self._service()
        if self._code is not None and time.ticks_diff(time.ticks_ms(), self._seen) < HOLD_MS:
            return self._code
        return None

    def name(self, code):
        """鍵碼 → 鍵名（left/right/up/down/ok）；沒記過就回傳空字串"""
        if code is None:
            return ""
        for k in KEY_NAMES:
            if self.keys.get(k) == code:
                return k
        return ""

    def busy(self):
        """正在收一串紅外線訊號嗎？"""
        return self._n > 0 and time.ticks_diff(time.ticks_us(), self._last) < GAP_US

    def wait_quiet(self):
        """如果正在收訊號，等它收完再繼續（最多等 QUIET_MAX_MS 毫秒）"""
        t0 = time.ticks_ms()
        while self.busy() and time.ticks_diff(time.ticks_ms(), t0) < QUIET_MAX_MS:
            time.sleep_ms(1)

    def show(self, oled):
        """更新 OLED：一次送 1/8 個畫面，每送一塊前先看有沒有紅外線訊號進來"""
        try:
            buf = oled.buffer
            w = oled.width
            pages = oled.pages
            wc = oled.write_cmd
            wd = oled.write_data
        except AttributeError:
            self.wait_quiet()
            oled.show()
            return
        if self._pages is None or self._pages_src is not buf:
            mv = memoryview(buf)
            self._pages = [mv[p * w:(p + 1) * w] for p in range(pages)]   # 先切好 8 塊，之後不用再配置記憶體
            self._pages_src = buf
        self.wait_quiet()
        # 跟 ssd1306.py 的 show() 一樣先設定範圍；之後資料分 8 次送，螢幕會自己接著往下寫
        wc(0x21)
        wc(0)
        wc(w - 1)
        wc(0x22)
        wc(0)
        wc(pages - 1)
        for p in range(pages):
            self.wait_quiet()
            wd(self._pages[p])

    def stop(self):
        """不再聽遙控器"""
        self._pin.irq(handler=None)


# ============================================
# 解碼（主程式這邊跑，不在中斷裡）
# ============================================

def _durations(buf, n):
    """時間戳 → 每一段的長度（微秒）。第 0 段是「亮」，之後亮暗交替。
    很短的雜訊段會跟前後合併，免得亮暗順序亂掉。"""
    raw = []
    for i in range(n - 1):
        raw.append(time.ticks_diff(buf[i + 1], buf[i]))
    i = 0
    while i + 1 < len(raw) and raw[i] < GLITCH_US:
        i += 2                      # 開頭的雜訊：一次丟兩段，亮暗順序才不會反過來
    out = []
    glitches = 0
    while i < len(raw):
        v = raw[i]
        if out and v < GLITCH_US and i + 1 < len(raw):
            out[-1] = out[-1] + v + raw[i + 1]     # 中間的雜訊：跟前後兩段併成一段
            i += 2
            glitches += 1
        else:
            out.append(v)
            i += 1
    if len(out) > 2 and out[-1] < GLITCH_US:
        out.pop()                   # 結尾的雜訊
    return out, glitches


def _nec(d):
    """NEC 格式：9 ms 亮＋4.5 ms 暗開頭，接 32 個位元；重複碼是 9 ms 亮＋2.25 ms 暗"""
    if len(d) < 2:
        return _NONE, None
    mark, space = d[0], d[1]
    # 開頭的亮可能因為中斷晚到而變短，放寬到 3 ms 起算（Samsung 的 4.5 ms 也一起收）
    if not (3000 <= mark <= 12000):
        return _NONE, None
    if 1600 <= space <= 3000 and len(d) <= 4:
        return _REPEAT, None
    if not (3300 <= space <= 5800):
        return _NONE, None
    if len(d) < 40:
        return _NONE, None               # 開頭像 NEC、但短很多（例如 JVC 的 16 位元）：交給下面「長短樣子」算號碼
    if len(d) < 2 + 64:
        return _BAD, None
    value = 0
    for i in range(32):
        m = d[2 + 2 * i]
        s = d[3 + 2 * i]
        if not (200 <= m <= 1300 and 200 <= s <= 2600):
            return _BAD, None
        if s > 1100:
            value |= 1 << i              # NEC 先送最低位
    b0 = value & 0xFF
    b1 = (value >> 8) & 0xFF
    b2 = (value >> 16) & 0xFF
    b3 = (value >> 24) & 0xFF
    if b2 ^ b3 != 0xFF:                  # 指令一定帶反碼；位址可以不帶（延伸 NEC）
        return _BAD, None
    return _FRAME, b0 | (b1 << 8) | (b2 << 16)


def _distance(d):
    """NEC 以外最常見的一類（Panasonic、JVC、Samsung……）：開頭一段長亮＋長暗，
    後面每個位元都是「一段短亮＋一段暗」，暗的短＝0、暗的長（約 3 倍）＝1。
    2026-11-23 實板量到的遙控器就是這種：開頭 3.4 ms 亮＋1.8 ms 暗，48 個位元，
    亮約 0.4 ms，暗約 0.47 ms（0）或 1.35 ms（1），按住時每 0.13 秒整串重送一次。
    檢查得很嚴：只要有一段長度不像樣（多半是程式剛好在忙、時間記晚了），
    就回報「訊號不完整」，寧可漏一次，也不要給出一個錯的號碼。"""
    n = len(d)
    if n < 2 + 2 * 12:
        return _NONE, None
    if d[0] < 1800 or d[1] < 1000:
        return _NONE, None               # 沒有長長的開頭：不是這一類
    marks = sorted(d[2::2])
    unit = marks[len(marks) // 2]        # 亮的長度取中位數當基準
    if not (200 <= unit <= 900):
        return _NONE, None
    nbits = (n - 2) // 2
    long_marks = 0
    for i in range(nbits):
        m = d[2 + 2 * i]
        if m * 10 > unit * 16:
            long_marks += 1
    if long_marks * 4 >= nbits:
        return _NONE, None               # 亮的長度有長有短（Sony 那一類）：交給「長短樣子」算號碼
    value = 0
    for i in range(nbits):
        m = d[2 + 2 * i]
        s = d[3 + 2 * i]
        if not (unit * 4 <= m * 10 <= unit * 19):
            return _BAD, None
        if s * 10 <= unit * 4:
            return _BAD, None
        if s * 10 <= unit * 21:
            pass                         # 短的暗：0
        elif s * 10 <= unit * 48:
            value |= 1 << i              # 長的暗：1
        else:
            return _BAD, None
    h = 0x811C9DC5
    v = value
    for _ in range((nbits + 7) // 8):
        h = ((h ^ (v & 0xFF)) * 0x01000193) & 0xFFFFFFFF
        v >>= 8
    h = ((h ^ nbits) * 0x01000193) & 0xFFFFFFFF
    return _FRAME, 0x1000000 | ((h ^ (h >> 24)) & 0xFFFFFF)


def _shape_code(d):
    """不是 NEC：把每一段分成「短」或「長」，再把整串短長算成一個號碼（FNV 雜湊）。
    - 開頭兩段（引導用的長亮、長暗）不算，它們每個鍵都一樣，長度又最容易跑掉。
    - 「短」的基準＝最短那一群的平均；超過基準 1.4 倍就算「長」。
      （電腦模擬：每段長度亂跳 ±20% 時，同一個鍵每次號碼都一樣）"""
    if len(d) < 8:
        return _NONE, None
    if 60 <= len(d) <= 72:
        return _BAD, None       # 段數跟 NEC 一樣、卻解不出來：多半是 NEC 收壞了，不要亂給號碼
    if len(d) > 120:
        d = d[:120]
    data = d[2:]
    shortest = min(data)
    total = 0
    count = 0
    for v in data:
        if v * 10 <= shortest * 16:           # 比最短的長不到 1.6 倍：算最短那一群
            total += v
            count += 1
    unit = total // count
    # 正常的遙控器訊號開頭都有一段很長的「亮」（至少約 3 個基準長）；RC5 沒有，但它的基準比較長（約 0.9 ms）。
    # 兩個都不是：多半是收到一半的 NEC（程式卡住時被切斷），不給號碼。
    if d[0] * 10 < unit * 28 and not (unit >= 750 and len(d) <= 30):
        return _BAD, None
    h = 0x811C9DC5
    for v in data:
        bit = 2 if v * 10 > unit * 14 else 1
        h = ((h ^ bit) * 0x01000193) & 0xFFFFFFFF
    h = ((h ^ len(d)) * 0x01000193) & 0xFFFFFFFF
    return _FRAME, 0x1000000 | ((h ^ (h >> 24)) & 0xFFFFFF)   # 加上 0x1000000，跟 NEC 的號碼分開


def decode(buf, n):
    """一串時間戳 → (種類, 鍵碼)"""
    if n < 3:
        return _NONE, None
    d, glitches = _durations(buf, n)
    kind, code = _nec(d)
    if kind != _NONE:
        return kind, code
    if glitches > 3:
        return _BAD, None       # 雜訊太多（多半是程式卡住、時間記錯了）：寧可不認，也不要給錯的號碼
    kind, code = _distance(d)
    if kind != _NONE:
        return kind, code
    if len(d) >= 40 and d[0] < 1800:
        return _BAD, None       # 很長一串卻沒有開頭：多半是只收到後半段，不給號碼
    return _shape_code(d)
