"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        BIST ANALİZ & HESAPLAMA MOTORU  V2.0                                ║
║                                                                              ║
║  İNDİKATÖRLER:                                                              ║
║    RSI · MACD · Stochastic · Williams%R · CCI · ADX · ATR                  ║
║    Bollinger Bantları · OBV · Hacim Profili · Fibonacci                     ║
║    Mum Formasyonları · Ichimoku · Supertrend · Vortex                       ║
║                                                                              ║
║  PUANLAMA:                                                                   ║
║    Çoklu zaman dilimi ağırlıklı skor                                        ║
║    Güven ve risk skoru                                                       ║
║    Hedef / Stop / Risk-Ödül hesaplama                                       ║
║    Olasılık tahmini (lojistik model)                                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

Kullanım:
    from bist_analysis_engine import analyze, TIMEFRAME_CONFIG
    sonuc = analyze("GARAN")
"""

import math
import logging

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# SABİTLER
# ══════════════════════════════════════════════════════════════════════════════
MIN_BARS = 80

TIMEFRAME_CONFIG = {
    "1G": {"lookback": 1,   "context": 40},
    "1H": {"lookback": 5,   "context": 45},
    "1A": {"lookback": 21,  "context": 70},
    "3A": {"lookback": 63,  "context": 130},
    "6A": {"lookback": 126, "context": 190},
    "1Y": {"lookback": 252, "context": 252},
}

TF_WEIGHTS = {"1G": 0.06, "1H": 0.10, "1A": 0.20, "3A": 0.25, "6A": 0.22, "1Y": 0.17}

# ══════════════════════════════════════════════════════════════════════════════
# TEMEL İNDİKATÖRLER
# ══════════════════════════════════════════════════════════════════════════════

def sma(d, p):
    """Basit Hareketli Ortalama."""
    if not d: return 0.0
    n = min(len(d), p)
    return sum(d[-n:]) / n


def ema(d, p):
    """Üssel Hareketli Ortalama (son değer)."""
    if not d: return 0.0
    if len(d) < p: return sum(d) / len(d)
    k = 2 / (p + 1)
    v = sum(d[:p]) / p
    for x in d[p:]:
        v = x * k + v * (1 - k)
    return v


def ema_series(d, p):
    """Tüm EMA dizisini döndür."""
    if len(d) < p: return []
    k = 2 / (p + 1)
    v = sum(d[:p]) / p
    result = [v]
    for x in d[p:]:
        v = x * k + v * (1 - k)
        result.append(v)
    return result


def wma(d, p):
    """Ağırlıklı Hareketli Ortalama."""
    n = min(len(d), p)
    if n == 0: return 0.0
    w = sum(range(1, n + 1))
    return sum((i + 1) * d[-n + i] for i in range(n)) / w


def hma(d, p):
    """Hull Hareketli Ortalama — daha az gecikmeli trend tespiti."""
    if len(d) < p: return sma(d, len(d))
    half_p = max(2, p // 2)
    sqrt_p = max(2, int(math.sqrt(p)))
    wma_half = [wma(d[:i+1], half_p) for i in range(len(d))]
    wma_full = [wma(d[:i+1], p)      for i in range(len(d))]
    diff = [2 * wma_half[i] - wma_full[i] for i in range(len(d))]
    return wma(diff, sqrt_p)


def wilder_rsi(prices, period=14):
    """Wilder RSI — standart uygulama."""
    if len(prices) < period + 1: return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[i])  / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0: return 100.0 if ag > 0 else 50.0
    return round(100 - 100 / (1 + ag / al), 2)


def rsi_divergence(prices, period=14, lookback=30):
    """
    RSI diverjans tespiti.
    Döner: 'bullish' (fiyat düşük - RSI yükseliyor),
            'bearish' (fiyat yüksek - RSI düşüyor),
            '' (diverjans yok)
    """
    n = min(len(prices), lookback)
    if n < period + 5: return ""
    seg = prices[-n:]
    rsi_vals = [wilder_rsi(seg[:i+1], period) for i in range(len(seg))]
    # Son 2 yerel dip/tepe karşılaştır
    price_low_1  = min(seg[-n//2:])
    price_low_2  = min(seg[-n//4:])
    rsi_low_1    = min(rsi_vals[-n//2:])
    rsi_low_2    = min(rsi_vals[-n//4:])
    price_high_1 = max(seg[-n//2:])
    price_high_2 = max(seg[-n//4:])
    rsi_high_1   = max(rsi_vals[-n//2:])
    rsi_high_2   = max(rsi_vals[-n//4:])

    if price_low_2 < price_low_1 and rsi_low_2 > rsi_low_1:
        return "bullish"
    if price_high_2 > price_high_1 and rsi_high_2 < rsi_high_1:
        return "bearish"
    return ""


def compute_macd(prices, fast=12, slow=26, signal=9):
    """MACD, Signal ve Histogram döndür."""
    if len(prices) < slow + signal: return 0.0, 0.0, 0.0
    ema_fast = ema_series(prices, fast)
    ema_slow = ema_series(prices, slow)
    offset = slow - fast
    macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
    if len(macd_line) < signal: return 0.0, 0.0, 0.0
    sig_series = ema_series(macd_line, signal)
    if not sig_series: return 0.0, 0.0, 0.0
    macd_val  = macd_line[-1]
    sig_val   = sig_series[-1]
    hist_val  = macd_val - sig_val
    return round(macd_val, 4), round(sig_val, 4), round(hist_val, 4)


def compute_stochastic(highs, lows, closes, k_period=14, d_period=3):
    """Stochastic %K ve %D döndür."""
    n = min(len(highs), len(lows), len(closes))
    if n < k_period: return 50.0, 50.0
    k_values = []
    for i in range(k_period - 1, n):
        h_max = max(highs[i - k_period + 1: i + 1])
        l_min = min(lows[i  - k_period + 1: i + 1])
        rng   = h_max - l_min
        k = 100 * (closes[i] - l_min) / rng if rng > 0 else 50.0
        k_values.append(k)
    if not k_values: return 50.0, 50.0
    k_val = k_values[-1]
    d_val = sum(k_values[-d_period:]) / min(d_period, len(k_values))
    return round(k_val, 2), round(d_val, 2)


def compute_williams_r(highs, lows, closes, period=14):
    """Williams %R döndür."""
    n = min(len(highs), len(lows), len(closes))
    if n < period: return -50.0
    h_max = max(highs[-period:])
    l_min = min(lows[-period:])
    rng   = h_max - l_min
    if rng == 0: return -50.0
    return round(-100 * (h_max - closes[-1]) / rng, 2)


def compute_cci(highs, lows, closes, period=20):
    """Commodity Channel Index."""
    n = min(len(highs), len(lows), len(closes))
    if n < period: return 0.0
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    tp_slice = tp[-period:]
    ma = sum(tp_slice) / period
    md = sum(abs(x - ma) for x in tp_slice) / period
    if md == 0: return 0.0
    return round((tp[-1] - ma) / (0.015 * md), 2)


def compute_atr(highs, lows, closes, period=14):
    """Average True Range."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1: return 0.0
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1])) for i in range(1, n)]
    return sum(trs[-period:]) / period


def compute_bollinger(prices, period=20, num_std=2.0):
    """Bollinger Bantları + %B + Squeeze."""
    if len(prices) < period:
        p = prices[-1]; return p, p, p, 0.5, 0.0
    w   = prices[-period:]
    ma  = sum(w) / period
    std = math.sqrt(sum((x - ma) ** 2 for x in w) / period)
    upper  = ma + num_std * std
    lower  = ma - num_std * std
    width  = upper - lower
    pct_b  = (prices[-1] - lower) / width if width > 0 else 0.5
    squeeze = std / ma * 100
    return round(upper, 2), round(ma, 2), round(lower, 2), round(pct_b, 3), round(squeeze, 3)


def compute_keltner_channel(highs, lows, closes, ema_period=20, atr_period=10, mult=2.0):
    """Keltner Kanalı — BB ile birlikte sıkışma tespitinde kullanılır."""
    if len(closes) < ema_period: return 0.0, 0.0, 0.0
    mid   = ema(closes, ema_period)
    atr_v = compute_atr(highs, lows, closes, atr_period)
    return round(mid + mult * atr_v, 2), round(mid, 2), round(mid - mult * atr_v, 2)


def compute_volatility(prices, annualize=False):
    """Yüzde volatilite (günlük veya yıllık)."""
    if len(prices) < 3: return 0.0
    rets = [(prices[i] - prices[i-1]) / prices[i-1]
            for i in range(1, len(prices)) if prices[i-1] > 0]
    if len(rets) < 2: return 0.0
    mean = sum(rets) / len(rets)
    var  = sum((r - mean) ** 2 for r in rets) / len(rets)
    vol  = math.sqrt(var)
    return vol * math.sqrt(252) * 100 if annualize else vol * 100


def compute_fibonacci_levels(highs, lows, lookback=60):
    """Fibonacci geri çekilme & uzantı seviyeleri."""
    n     = min(len(highs), len(lows), lookback)
    h_max = max(highs[-n:])
    l_min = min(lows[-n:])
    rng   = h_max - l_min
    levels = {
        "0.0":   round(h_max, 2),
        "23.6":  round(h_max - rng * 0.236, 2),
        "38.2":  round(h_max - rng * 0.382, 2),
        "50.0":  round(h_max - rng * 0.500, 2),
        "61.8":  round(h_max - rng * 0.618, 2),
        "78.6":  round(h_max - rng * 0.786, 2),
        "100.0": round(l_min, 2),
        "127.2": round(l_min - rng * 0.272, 2),
        "161.8": round(l_min - rng * 0.618, 2),
    }
    return levels, h_max, l_min


def compute_obv(closes, volumes):
    """On-Balance Volume eğimi (son 10 bar)."""
    if len(closes) < 2 or len(volumes) < 2: return 0.0
    obv = 0.0
    obv_vals = [0.0]
    for i in range(1, min(len(closes), len(volumes))):
        if   closes[i] > closes[i-1]: obv += volumes[i]
        elif closes[i] < closes[i-1]: obv -= volumes[i]
        obv_vals.append(obv)
    recent = obv_vals[-10:]
    if len(recent) >= 2:
        return round((recent[-1] - recent[0]) / len(recent), 0)
    return 0.0


def compute_mfi(highs, lows, closes, volumes, period=14):
    """
    Money Flow Index — hacim ağırlıklı RSI.
    0-100 arası; <20 aşırı satım, >80 aşırı alım.
    """
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n < period + 1: return 50.0
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    raw_mf = [tp[i] * volumes[i] for i in range(n)]
    pos_mf = neg_mf = 0.0
    for i in range(n - period, n):
        if tp[i] > tp[i-1]:  pos_mf += raw_mf[i]
        elif tp[i] < tp[i-1]: neg_mf += raw_mf[i]
    if neg_mf == 0: return 100.0
    mfr = pos_mf / neg_mf
    return round(100 - 100 / (1 + mfr), 2)


def compute_adx(highs, lows, closes, period=14):
    """Average Directional Index (ADX) + +DI / -DI."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2: return 20.0, 0.0, 0.0
    tr_list, pdm_list, ndm_list = [], [], []
    for i in range(1, n):
        tr  = max(highs[i] - lows[i],
                  abs(highs[i] - closes[i-1]),
                  abs(lows[i]  - closes[i-1]))
        pdm = max(highs[i] - highs[i-1], 0)
        ndm = max(lows[i-1] - lows[i], 0)
        if pdm > ndm:    ndm = 0.0
        elif ndm > pdm:  pdm = 0.0
        else:            pdm = ndm = 0.0
        tr_list.append(tr); pdm_list.append(pdm); ndm_list.append(ndm)

    atr_v = sum(tr_list[:period]) / period
    pdi_v = sum(pdm_list[:period]) / period
    ndi_v = sum(ndm_list[:period]) / period
    dx_vals = []
    for i in range(period, len(tr_list)):
        atr_v = (atr_v * (period - 1) + tr_list[i])  / period
        pdi_v = (pdi_v * (period - 1) + pdm_list[i]) / period
        ndi_v = (ndi_v * (period - 1) + ndm_list[i]) / period
        pdi   = 100 * pdi_v / atr_v if atr_v > 0 else 0
        ndi   = 100 * ndi_v / atr_v if atr_v > 0 else 0
        denom = pdi + ndi
        dx    = 100 * abs(pdi - ndi) / denom if denom > 0 else 0
        dx_vals.append((dx, pdi, ndi))
    if not dx_vals: return 20.0, 0.0, 0.0
    adx_val = sum(d[0] for d in dx_vals[-period:]) / min(period, len(dx_vals))
    return round(adx_val, 2), round(dx_vals[-1][1], 2), round(dx_vals[-1][2], 2)


def compute_supertrend(highs, lows, closes, period=10, multiplier=3.0):
    """
    Supertrend göstergesi.
    Döner: (yön: 1=yükseliş/-1=düşüş, supertrend_fiyatı)
    """
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2: return 1, closes[-1] if closes else 0
    atr_vals = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        atr_vals.append(tr)

    # Wilder smoothing için ATR dizisi
    atr_smooth = [sum(atr_vals[:period]) / period]
    for i in range(period, len(atr_vals)):
        atr_smooth.append((atr_smooth[-1] * (period - 1) + atr_vals[i]) / period)

    direction = 1
    st_val    = closes[period]
    for i in range(len(atr_smooth)):
        idx     = i + period
        if idx >= n: break
        hl2     = (highs[idx] + lows[idx]) / 2
        upper_b = hl2 + multiplier * atr_smooth[i]
        lower_b = hl2 - multiplier * atr_smooth[i]
        if closes[idx] > st_val and direction == -1:
            direction = 1
        elif closes[idx] < st_val and direction == 1:
            direction = -1
        st_val = lower_b if direction == 1 else upper_b
    return direction, round(st_val, 2)


def compute_vortex(highs, lows, closes, period=14):
    """
    Vortex Indicator (VI+ ve VI-).
    VI+ > VI- → yükseliş trendi
    """
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1: return 1.0, 1.0
    vm_plus = vm_minus = tr_sum = 0.0
    for i in range(n - period, n):
        tr       = max(highs[i] - lows[i],
                       abs(highs[i] - closes[i-1]),
                       abs(lows[i]  - closes[i-1]))
        vp       = abs(highs[i] - lows[i-1])
        vm       = abs(lows[i]  - highs[i-1])
        vm_plus  += vp; vm_minus += vm; tr_sum += tr
    if tr_sum == 0: return 1.0, 1.0
    return round(vm_plus / tr_sum, 3), round(vm_minus / tr_sum, 3)


def compute_ichimoku(highs, lows, closes,
                     tenkan=9, kijun=26, senkou_b=52, chikou=26):
    """
    Ichimoku Bulut bileşenleri.
    Döner: (tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou_span, cloud_signal)
    cloud_signal: 'bullish' / 'bearish' / 'neutral'
    """
    n = min(len(highs), len(lows), len(closes))
    def hl_avg(h, l, period):
        if n < period: return (highs[-1] + lows[-1]) / 2
        return (max(h[-period:]) + min(l[-period:])) / 2

    t_sen = hl_avg(highs, lows, tenkan)
    k_sen = hl_avg(highs, lows, kijun)
    s_a   = (t_sen + k_sen) / 2
    s_b   = hl_avg(highs, lows, senkou_b)
    chikou_val = closes[-1]  # Gecikmeli kapanış (çizim için)

    last = closes[-1]
    if last > max(s_a, s_b):   cloud_signal = "bullish"
    elif last < min(s_a, s_b): cloud_signal = "bearish"
    else:                       cloud_signal = "neutral"

    return round(t_sen, 2), round(k_sen, 2), round(s_a, 2), round(s_b, 2), \
           round(chikou_val, 2), cloud_signal


def compute_volume_profile(closes, volumes, bins=10):
    """Hacim yoğunluk bölgelerini döndür (POC, VAL, VAH)."""
    if len(closes) < bins or not volumes: return None, None, None
    mn = min(closes); mx = max(closes)
    if mn == mx: return None, None, None
    step = (mx - mn) / bins
    bucket_vol = [0.0] * bins
    for c, v in zip(closes, volumes):
        idx = min(int((c - mn) / step), bins - 1)
        bucket_vol[idx] += v
    poc_idx  = bucket_vol.index(max(bucket_vol))
    poc_low  = mn + poc_idx * step
    poc      = poc_low + step / 2
    # Value Area (70%)
    total     = sum(bucket_vol)
    va_target = total * 0.70
    va_accum  = bucket_vol[poc_idx]
    lo_ptr = hi_ptr = poc_idx
    while va_accum < va_target:
        add_lo = bucket_vol[lo_ptr - 1] if lo_ptr > 0 else 0
        add_hi = bucket_vol[hi_ptr + 1] if hi_ptr < bins - 1 else 0
        if add_lo == 0 and add_hi == 0: break
        if add_lo >= add_hi:
            lo_ptr -= 1; va_accum += add_lo
        else:
            hi_ptr += 1; va_accum += add_hi
    val = mn + lo_ptr * step
    vah = mn + (hi_ptr + 1) * step
    return round(poc, 2), round(val, 2), round(vah, 2)


# ══════════════════════════════════════════════════════════════════════════════
# MUM FORMASYONU TESPİTİ
# ══════════════════════════════════════════════════════════════════════════════

def detect_candlestick_patterns(opens, highs, lows, closes):
    """
    Son 3 bardaki formasyon tespiti.
    Ek formasyonlar: Dark Cloud Cover, Piercing Line,
                     Evening Star, Three Black Crows, Tweezer Top/Bottom
    """
    n = min(len(opens), len(highs), len(lows), len(closes))
    if n < 3: return ""
    o1, h1, l1, c1 = opens[n-3], highs[n-3], lows[n-3], closes[n-3]
    o2, h2, l2, c2 = opens[n-2], highs[n-2], lows[n-2], closes[n-2]
    o3, h3, l3, c3 = opens[n-1], highs[n-1], lows[n-1], closes[n-1]

    body3  = abs(c3 - o3)
    range3 = h3 - l3
    body2  = abs(c2 - o2)
    range2 = h2 - l2
    body1  = abs(c1 - o1)

    patterns = []

    # ── Tek Bar Formasyonları ──────────────────────────────────────────────
    if range3 > 0:
        lower_shadow = min(o3, c3) - l3
        upper_shadow = h3 - max(o3, c3)
        # Çekiç / Asılan Adam
        if lower_shadow > 2 * body3 and upper_shadow < body3 * 0.3:
            patterns.append("🔨 Çekiç")
        # Kayan Yıldız
        if upper_shadow > 2 * body3 and lower_shadow < body3 * 0.3:
            patterns.append("💫 Kayan Yıldız")
        # Spinning Top
        if body3 < range3 * 0.25 and lower_shadow > body3 and upper_shadow > body3:
            patterns.append("🌀 Spinning Top")

    # Doji
    if range3 > 0 and body3 / range3 < 0.10:
        patterns.append("✳️ Doji")

    # ── İki Bar Formasyonları ──────────────────────────────────────────────
    # Bullish Engulfing
    if c2 < o2 and c3 > o3 and o3 < c2 and c3 > o2:
        patterns.append("📈 Yutan Boğa")
    # Bearish Engulfing
    if c2 > o2 and c3 < o3 and o3 > c2 and c3 < o2:
        patterns.append("📉 Yutan Ayı")
    # Dark Cloud Cover
    if (c2 > o2 and c3 < o3
            and o3 > h2
            and c3 < (o2 + c2) / 2
            and c3 > o2):
        patterns.append("🌑 Kara Bulut Örtüsü")
    # Piercing Line
    if (c2 < o2 and c3 > o3
            and o3 < l2
            and c3 > (o2 + c2) / 2
            and c3 < o2):
        patterns.append("🌤️ Delici Çizgi")
    # Tweezer Bottom
    if c2 < o2 and abs(l2 - l3) / max(l2, 0.01) < 0.005 and c3 > o3:
        patterns.append("🔩 Cımbız Dip")
    # Tweezer Top
    if c2 > o2 and abs(h2 - h3) / max(h2, 0.01) < 0.005 and c3 < o3:
        patterns.append("🔩 Cımbız Tepe")

    # ── Üç Bar Formasyonları ──────────────────────────────────────────────
    # Morning Star
    if (c1 < o1 and abs(c2 - o2) < body1 * 0.3
            and c3 > o3 and c3 > (o1 + c1) / 2):
        patterns.append("🌅 Sabah Yıldızı")
    # Evening Star
    if (c1 > o1 and abs(c2 - o2) < body1 * 0.3
            and c3 < o3 and c3 < (o1 + c1) / 2):
        patterns.append("🌆 Akşam Yıldızı")
    # Three White Soldiers
    if (c3 > o3 > c2 > o2 > c1 > o1
            and c3 > c2 > c1
            and body3 > range3 * 0.5 and body2 > range2 * 0.5):
        patterns.append("⚔️ 3 Beyaz Asker")
    # Three Black Crows
    if (c3 < o3 < c2 < o2 < c1 < o1
            and c3 < c2 < c1
            and body3 > range3 * 0.5 and body2 > range2 * 0.5):
        patterns.append("🐦 3 Siyah Karga")
    # Morning Doji Star
    if (c1 < o1 and body2 / max(range2, 0.0001) < 0.10
            and c3 > o3 and c3 > (o1 + c1) / 2):
        patterns.append("⭐ Sabah Doji Yıldızı")

    return ", ".join(patterns) if patterns else ""


# ══════════════════════════════════════════════════════════════════════════════
# PUANLAMA MOTORU
# ══════════════════════════════════════════════════════════════════════════════

def score_timeframe(prices, lookback, context_days, benchmark=None,
                    volumes=None, highs=None, lows=None):
    """
    Tek zaman dilimi için kapsamlı skor hesapla.
    Yeni eklenenler: MFI, Supertrend, Vortex, Ichimoku, HMA, RSI diverjansı
    """
    if len(prices) < max(lookback + 1, 30): return None
    ctx_len = min(len(prices), context_days)
    ctx_p   = prices[-ctx_len:]
    ctx_v   = volumes[-ctx_len:] if volumes and len(volumes) >= ctx_len else []
    ctx_h   = highs[-ctx_len:]   if highs   and len(highs)   >= ctx_len else ctx_p
    ctx_l   = lows[-ctx_len:]    if lows    and len(lows)    >= ctx_len else ctx_p

    last    = ctx_p[-1]
    ref     = prices[-(lookback + 1)]
    if ref == 0: return None
    chg_pct = (last - ref) / ref * 100

    # ── Temel indikatörler ──────────────────────────────────────────────
    rsi_val = wilder_rsi(ctx_p)
    ma10    = sma(ctx_p, 10)
    ma20    = sma(ctx_p, 20)
    ma30    = sma(ctx_p, 30)
    ma50    = sma(ctx_p, 50)
    ema9    = ema(ctx_p, 9)
    ema21   = ema(ctx_p, 21)
    hma_val = hma(ctx_p, 20)                         # YENİ: HMA
    vol_d   = compute_volatility(ctx_p, False)
    vol_a   = compute_volatility(ctx_p, True)
    up_days = sum(1 for i in range(1, len(ctx_p)) if ctx_p[i] > ctx_p[i-1])
    up_ratio= up_days / max(1, len(ctx_p) - 1)
    peak    = max(ctx_p)
    drawdown= (peak - last) / peak * 100 if peak > 0 else 0

    # MACD
    macd_val, macd_sig, macd_hist = compute_macd(ctx_p)
    macd_bullish  = macd_val > macd_sig
    macd_cross_up = macd_hist > 0

    # Stochastic
    stoch_k, stoch_d = compute_stochastic(ctx_h, ctx_l, ctx_p)

    # Williams %R
    wpr = compute_williams_r(ctx_h, ctx_l, ctx_p)

    # CCI
    cci_val = compute_cci(ctx_h, ctx_l, ctx_p)

    # ADX
    adx_val, pdi_val, ndi_val = compute_adx(ctx_h, ctx_l, ctx_p)
    strong_trend = adx_val > 25

    # Bollinger
    bb_upper, bb_mid, bb_lower, pct_b, bb_squeeze = compute_bollinger(ctx_p)

    # Keltner — BB sıkışma doğrulaması
    kc_upper, kc_mid, kc_lower = compute_keltner_channel(ctx_h, ctx_l, ctx_p)
    true_squeeze = (bb_upper < kc_upper and bb_lower > kc_lower)  # YENİ

    # OBV
    obv_slope = compute_obv(ctx_p, ctx_v) if ctx_v else 0.0

    # MFI  YENİ
    mfi_val = compute_mfi(ctx_h, ctx_l, ctx_p, ctx_v) if ctx_v else 50.0

    # Supertrend  YENİ
    st_dir, st_price = compute_supertrend(ctx_h, ctx_l, ctx_p)

    # Vortex  YENİ
    vi_plus, vi_minus = compute_vortex(ctx_h, ctx_l, ctx_p)

    # Ichimoku  YENİ
    t_sen, k_sen, s_a, s_b, _, cloud_sig = compute_ichimoku(ctx_h, ctx_l, ctx_p)

    # RSI diverjansı  YENİ
    rsi_div = rsi_divergence(ctx_p)

    # Göreceli güç
    rel_str = 0.0
    if benchmark and len(benchmark) >= lookback + 1:
        bm_ref  = benchmark[-(lookback + 1)]
        bm_last = benchmark[-1]
        if bm_ref > 0 and bm_last > 0:
            rel_str = ((last / ref) / (bm_last / bm_ref) - 1.0) * 100

    # ══════════════════════════════════════════════════════════════════════
    # PUANLAMA (0–10 üzerinden)
    # ══════════════════════════════════════════════════════════════════════
    score = 5.0

    # 1. Fiyat değişimi (max ±3)
    if   chg_pct > 10:  score += 3.0
    elif chg_pct >  5:  score += 2.5
    elif chg_pct >  2:  score += 1.5
    elif chg_pct >  0:  score += 0.8
    elif chg_pct < -10: score -= 3.0
    elif chg_pct <  -5: score -= 2.5
    elif chg_pct <  -2: score -= 1.5
    elif chg_pct <   0: score -= 0.8

    # 2. Göreceli güç (max ±1)
    if   rel_str > 3:  score += 1.0
    elif rel_str > 1:  score += 0.5
    elif rel_str < -3: score -= 1.0
    elif rel_str < -1: score -= 0.5

    # 3. Trend sinyalleri (max ±2)
    tsig = 0
    if last > ema9:   tsig += 1
    if ema9 > ema21:  tsig += 1
    if last > hma_val: tsig += 1                           # YENİ: HMA
    if last > ma50 and len(ctx_p) >= 50: tsig += 1
    if ma10 > ma30:   tsig += 1
    if up_ratio >= 0.58: tsig += 1
    elif up_ratio <= 0.42: tsig -= 2
    if tsig >= 5:   score += 2.0
    elif tsig >= 4: score += 1.7
    elif tsig >= 3: score += 1.0
    elif tsig >= 2: score += 0.5
    elif tsig <= -2: score -= 2.0
    elif tsig <= -1: score -= 1.0

    # 4. RSI (max ±1)
    if   rsi_val < 30: score += 1.0
    elif rsi_val < 40: score += 0.5
    elif 50 <= rsi_val <= 65: score += 0.5
    elif rsi_val > 75: score -= 1.0
    elif rsi_val > 70: score -= 0.5

    # 5. RSI Diverjansı  YENİ (max ±0.8)
    if rsi_div == "bullish":  score += 0.8
    elif rsi_div == "bearish": score -= 0.8

    # 6. MACD (max ±1)
    if macd_bullish and macd_cross_up:                score += 1.0
    elif macd_bullish:                                score += 0.5
    elif not macd_bullish and not macd_cross_up:      score -= 1.0
    elif not macd_bullish:                            score -= 0.5

    # 7. Stochastic (max ±0.8)
    if   stoch_k < 20 and stoch_k > stoch_d: score += 0.8
    elif stoch_k < 30:                        score += 0.4
    elif stoch_k > 80 and stoch_k < stoch_d: score -= 0.8
    elif stoch_k > 70:                        score -= 0.4

    # 8. CCI (max ±0.5)
    if   cci_val < -100: score += 0.5
    elif cci_val >  100: score -= 0.5

    # 9. ADX (max ±0.5)
    if strong_trend:
        if pdi_val > ndi_val: score += 0.5
        else:                 score -= 0.5

    # 10. Bollinger (max ±0.5)
    if   pct_b < 0.05: score += 0.5
    elif pct_b > 0.95: score -= 0.5

    # 11. Hacim oranı (max ±0.8)
    if ctx_v and len(ctx_v) >= 20:
        avg_vol = sum(ctx_v[-20:-5]) / 15 if sum(ctx_v[-20:-5]) > 0 else 1
        vr = (sum(ctx_v[-5:]) / 5) / avg_vol
        if chg_pct > 0 and vr >= 2.0:  score += 0.8
        elif chg_pct > 0 and vr >= 1.5: score += 0.4
        if chg_pct < 0 and vr >= 2.0:  score -= 0.8
        elif chg_pct < 0 and vr >= 1.5: score -= 0.4

    # 12. OBV (max ±0.5)
    if   obv_slope > 0: score += 0.3
    elif obv_slope < 0: score -= 0.3

    # 13. MFI  YENİ (max ±0.6)
    if   mfi_val < 20: score += 0.6
    elif mfi_val < 35: score += 0.3
    elif mfi_val > 80: score -= 0.6
    elif mfi_val > 65: score -= 0.3

    # 14. Supertrend  YENİ (max ±0.7)
    if   st_dir == 1:  score += 0.7
    elif st_dir == -1: score -= 0.7

    # 15. Vortex  YENİ (max ±0.5)
    if   vi_plus > vi_minus: score += 0.5
    elif vi_minus > vi_plus: score -= 0.5

    # 16. Ichimoku  YENİ (max ±0.7)
    if   cloud_sig == "bullish": score += 0.7
    elif cloud_sig == "bearish": score -= 0.7

    # 17. BB Gerçek Sıkışması (Keltner)  YENİ (max +0.5)
    if true_squeeze: score += 0.5

    # 18. Drawdown cezası
    if drawdown > 20: score -= 1.5
    elif drawdown > 12: score -= 0.8

    # 19. Volatilite cezası
    if vol_a > 70: score -= 1.5
    elif vol_a > 50: score -= 0.8

    score = round(max(0.5, min(10.0, score)), 1)

    # ── GÜVEN SKORU ────────────────────────────────────────────────────
    bullish_signals = sum([
        chg_pct > 0,
        last > ma10,
        ma10 > ma30,
        macd_bullish,
        stoch_k < 50,
        rsi_val < 60,
        obv_slope > 0,
        pdi_val > ndi_val,
        st_dir == 1,            # YENİ
        vi_plus > vi_minus,     # YENİ
        cloud_sig == "bullish", # YENİ
        mfi_val < 50,           # YENİ
    ])
    conf = 35 + bullish_signals * 5
    if 45 <= rsi_val <= 65: conf += 8
    elif rsi_val < 30 or rsi_val > 75: conf -= 12
    conf -= max(0, (vol_d - 2.5) * 8)
    if strong_trend: conf += 5
    if rsi_div == "bullish": conf += 6    # YENİ
    if rsi_div == "bearish": conf -= 6   # YENİ
    conf = int(max(5, min(95, conf)))

    # ── RİSK SKORU ─────────────────────────────────────────────────────
    risk = 0
    if vol_a > 65:  risk += 3
    elif vol_a > 45: risk += 2
    elif vol_a > 30: risk += 1
    if vol_d > 4.0:  risk += 2
    elif vol_d > 2.5: risk += 1
    if abs(chg_pct) > 8: risk += 1
    if rsi_val <= 25 or rsi_val >= 78: risk += 1
    if drawdown > 20: risk += 1
    if not strong_trend and abs(vi_plus - vi_minus) < 0.05: risk += 1  # YENİ
    risk_lbl = "DÜŞÜK" if risk <= 2 else "ORTA" if risk <= 5 else "YÜKSEK"

    # ── DURUM ETİKETİ ───────────────────────────────────────────────────
    if   score >= 8.5: durum, emoji = "🚀 KESİN AL", "🟢"
    elif score >= 7.0: durum, emoji = "🍀 AL",        "✅"
    elif score >= 5.5: durum, emoji = "⚪ İZLE/TUT",  "⚪"
    elif score >= 3.5: durum, emoji = "⚠️  SAT/İZLE", "🟠"
    else:              durum, emoji = "💀 KESİN SAT", "🔴"

    return {
        "puan": score, "durum": durum, "emoji": emoji,
        "degisim": round(chg_pct, 2), "rsi": rsi_val,
        "macd": macd_val, "macd_sig": macd_sig, "macd_hist": macd_hist,
        "stoch_k": stoch_k, "stoch_d": stoch_d,
        "wpr": wpr, "cci": cci_val, "adx": adx_val,
        "pct_b": round(pct_b, 3), "bb_squeeze": bb_squeeze,
        "volatilite": round(vol_d, 2), "volatilite_yillik": round(vol_a, 2),
        "trend_kalite": round(up_ratio * 100, 2), "drawdown": round(drawdown, 2),
        "rel_guc": round(rel_str, 2), "guven_skoru": conf,
        "risk_skoru": risk, "risk_seviyesi": risk_lbl,
        "obv_slope": round(obv_slope, 0), "tsig": tsig,
        # Yeni alanlar
        "mfi": mfi_val, "supertrend_dir": st_dir, "supertrend_price": st_price,
        "vi_plus": vi_plus, "vi_minus": vi_minus,
        "cloud_signal": cloud_sig, "ichimoku_t": t_sen, "ichimoku_k": k_sen,
        "rsi_divergence": rsi_div, "true_squeeze": true_squeeze,
        "hma": round(hma_val, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# AĞIRLIKLI KOMPOZIT HESAPLAMALAR
# ══════════════════════════════════════════════════════════════════════════════

def weighted_score(tf_results):
    """Zaman dilimi ağırlıklı bileşik puan."""
    tw = ts = 0.0
    for tf, w in TF_WEIGHTS.items():
        if tf in tf_results:
            ts += tf_results[tf]["puan"] * w
            tw += w
    return round(ts / tw, 2) if tw > 0 else 5.0


def composite_confidence(tf_results):
    """Ağırlıklı güven skoru."""
    tw = tc = 0.0
    for tf, w in TF_WEIGHTS.items():
        if tf in tf_results:
            tc += tf_results[tf]["guven_skoru"] * w
            tw += w
    return int(tc / tw) if tw > 0 else 50


def composite_risk(tf_results):
    """Ağırlıklı risk skoru."""
    tw = tr = 0.0
    for tf, w in TF_WEIGHTS.items():
        if tf in tf_results:
            tr += tf_results[tf]["risk_skoru"] * w
            tw += w
    return round(tr / tw, 1) if tw > 0 else 3.0


def count_aligned_tfs(tf_results, threshold=6.5):
    """Kaç zaman dilimi yükseliş sinyali veriyor?"""
    return sum(1 for d in tf_results.values() if d["puan"] >= threshold)


def estimate_prob_up(score, conf, risk, aligned_tfs, total_tfs):
    """
    Lojistik model ile yükseliş olasılığı tahmini.
    Yeni: rsi_divergence ve supertrend bilgisi doğrudan score/conf içinde
    zaten yansıyor, ek parametre gerekmez.
    """
    z = (
        (score - 5.5) / 1.5
        + (conf - 55) / 25
        - risk * 0.28
        + (aligned_tfs / max(total_tfs, 1) - 0.5) * 2.0
    )
    return max(0.02, min(0.98, 1 / (1 + math.exp(-z))))


# ══════════════════════════════════════════════════════════════════════════════
# HEDEF & STOP HESAPLAMA
# ══════════════════════════════════════════════════════════════════════════════

def build_prediction(closes, highs, lows, opens, volumes, score, rsi_val, conf, risk):
    """
    Fiyat tahmini: Hedef, Stop-Loss, Risk/Ödül, Aksiyon.
    Yeni: Supertrend tabanlı dinamik stop, Ichimoku destek/direnç
    """
    last    = closes[-1]
    atr_val = compute_atr(highs, lows, closes)
    bb_upper, bb_mid, bb_lower, pct_b, _ = compute_bollinger(closes)
    fib_levels, sw_high, sw_low = compute_fibonacci_levels(highs, lows, 60)
    sw_rng  = sw_high - sw_low
    fib_127 = sw_low + sw_rng * 1.272
    fib_162 = sw_low + sw_rng * 1.618

    poc, val, vah = compute_volume_profile(closes[-120:], volumes[-120:] if volumes else [])
    macd_v, macd_s, macd_h     = compute_macd(closes)
    adx_v, pdi_v, ndi_v         = compute_adx(highs, lows, closes)
    stoch_k, stoch_d             = compute_stochastic(highs, lows, closes)
    st_dir, st_price             = compute_supertrend(highs, lows, closes)      # YENİ
    _, k_sen, _, _, _, cloud_sig = compute_ichimoku(highs, lows, closes)        # YENİ
    mfi_val = compute_mfi(highs, lows, closes, volumes) if volumes else 50.0    # YENİ

    # ── Hedef belirle ──────────────────────────────────────────────────
    if   score >= 8.5: target = fib_162;  horizon = "3-6 hafta"
    elif score >= 7.0: target = fib_127;  horizon = "2-4 hafta"
    elif score >= 5.5: target = sw_high;  horizon = "2-3 hafta"
    elif score >= 4.0: target = bb_upper; horizon = "1-2 hafta"
    else:              target = bb_mid;   horizon = "1 hafta"

    if target <= last * 1.005:
        momentum = max(0.03, (closes[-1] - closes[-21]) / closes[-21] if len(closes) >= 22 else 0.03)
        target = last * (1 + max(momentum, 0.04))

    # ── Stop-Loss ──────────────────────────────────────────────────────
    atr_mult = 1.2 if score >= 8 else (1.5 if score >= 6.5 else 2.0)
    stop = last - atr_mult * atr_val

    # Supertrend desteğine snap  YENİ
    if st_dir == 1 and st_price < last and abs(st_price - stop) / last < 0.04:
        stop = st_price

    # Fibonacci 61.8 desteğine snap
    fib_618 = fib_levels.get("61.8", stop)
    if fib_618 < last and abs(fib_618 - stop) / last < 0.03:
        stop = fib_618

    # Kijun-Sen (Ichimoku) desteğine snap  YENİ
    if k_sen < last and abs(k_sen - stop) / last < 0.04:
        stop = max(stop, k_sen * 0.995)

    if stop >= last: stop = last * 0.95

    # ── Destek & Direnç ────────────────────────────────────────────────
    direnc30 = max(closes[-30:])
    destek30 = min(closes[-30:])
    if poc:
        destek30 = min(destek30, val) if val else destek30

    bek_get  = (target - last) / last * 100
    risk_pct = (last - stop) / last * 100
    rr       = bek_get / risk_pct if risk_pct > 0 else 0

    prob_up = estimate_prob_up(score, conf, risk, 0, 1)

    # ── Aksiyon kararı (çok faktörlü) ─────────────────────────────────
    if   score >= 8.5 and rsi_val < 72 and rr >= 1.5:  aksiyon = "🚀 GÜÇLÜ AL"
    elif score >= 7.0 and rsi_val < 74 and rr >= 1.2:  aksiyon = "✅ AL"
    elif score >= 5.5 and rr >= 1.0:                   aksiyon = "⏳ BEKLE/İZLE"
    elif score <= 3.5:                                  aksiyon = "🔴 SAT/ÇIKIŞ"
    else:                                               aksiyon = "⚪ NÖTR"

    if rsi_val > 78:
        aksiyon = "⚠️  AŞIRI ALIM"
    elif rsi_val < 22 and score >= 5.5:
        aksiyon = "💎 AŞIRI SATIM AL"

    # Supertrend + MFI onayı ile skor yükseltme/düşürme  YENİ
    if st_dir == -1 and cloud_sig == "bearish" and aksiyon in ("✅ AL", "⏳ BEKLE/İZLE"):
        aksiyon = "⚠️  DİKKATLİ — Trend Olumsuz"
    if mfi_val < 20 and rsi_val < 35 and "AŞIRI SATIM" not in aksiyon:
        aksiyon += " 💧MFI Aşırı Satım"

    # Mum formasyonu
    pattern = detect_candlestick_patterns(opens, highs, lows, closes)

    return {
        "fiyat":    round(last, 2),
        "hedef":    round(target, 2),
        "stop":     round(stop, 2),
        "bek_get":  round(bek_get, 2),
        "risk_pct": round(risk_pct, 2),
        "rr":       round(rr, 2),
        "prob_up":  round(prob_up * 100, 1),
        "horizon":  horizon,
        "aksiyon":  aksiyon,
        "destek":   round(destek30, 2),
        "direnc":   round(direnc30, 2),
        "upper_bb": round(bb_upper, 2),
        "lower_bb": round(bb_lower, 2),
        "mid_bb":   round(bb_mid, 2),
        "atr":      round(atr_val, 2),
        "pct_b":    round(pct_b, 3),
        "poc":      poc, "val": val, "vah": vah,
        "fib":      {k: v for k, v in fib_levels.items()},
        "sw_high":  round(sw_high, 2), "sw_low": round(sw_low, 2),
        "macd":     round(macd_v, 4), "macd_sig": round(macd_s, 4),
        "macd_hist": round(macd_h, 4),
        "adx":      round(adx_v, 2), "stoch_k": stoch_k, "stoch_d": stoch_d,
        "pattern":  pattern,
        # Yeni alanlar
        "supertrend_dir":   st_dir,
        "supertrend_price": st_price,
        "cloud_signal":     cloud_sig,
        "mfi":              mfi_val,
        "ichimoku_k":       round(k_sen, 2),
    }


def action_bucket(action_text):
    """Aksiyon metnini tek kategoriye indirger."""
    a = (action_text or "").upper()
    if "AŞIRI ALIM" in a:    return "overbought"
    if "SAT" in a or "ÇIKIŞ" in a: return "sell"
    if any(x in a for x in ("GÜÇLÜ AL", "KESİN AL", "✅ AL", "🍀 AL", "AŞIRI SATIM AL")):
        return "buy"
    if any(x in a for x in ("BEKLE", "İZLE", "NÖTR")):  return "wait"
    return "neutral"


# ══════════════════════════════════════════════════════════════════════════════
# ANA ANALİZ FONKSİYONU
# ══════════════════════════════════════════════════════════════════════════════

def analyze(symbol, closes, volumes, highs, lows, opens, benchmark=None):
    """
    Sembol analizini gerçekleştirir.
    Veri parametre olarak alınır (fetch bağımsızdır).

    Döner: dict (tüm analiz sonuçları) veya None
    """
    if len(closes) < MIN_BARS:
        log.warning(f"{symbol}: yetersiz veri ({len(closes)} bar)")
        return None

    tf_results = {}
    for tf, cfg in TIMEFRAME_CONFIG.items():
        res = score_timeframe(closes, cfg["lookback"], cfg["context"],
                              benchmark, volumes, highs, lows)
        if res:
            tf_results[tf] = res

    if not tf_results: return None

    score       = weighted_score(tf_results)
    conf        = composite_confidence(tf_results)
    w_risk      = composite_risk(tf_results)
    aligned_tfs = count_aligned_tfs(tf_results)

    first_tf = tf_results.get("1A", list(tf_results.values())[0])
    risk_v   = first_tf["risk_skoru"]
    rsi_v    = first_tf["rsi"]

    pred = build_prediction(closes, highs, lows, opens, volumes,
                            score, rsi_v, conf, w_risk)

    pred["prob_up"] = round(
        estimate_prob_up(score, conf, w_risk, aligned_tfs, len(tf_results)) * 100, 1
    )

    return {
        "hisse":           symbol.upper().replace(".IS", ""),
        "puan":            score,
        "rsi":             rsi_v,
        "guven_skoru":     conf,
        "risk_skoru":      w_risk,
        "risk_skoru_1a":   risk_v,
        "w_risk":          w_risk,
        "aligned_tfs":     aligned_tfs,
        "toplam_tfs":      len(tf_results),
        "zaman_dilimleri": tf_results,
        "closes_hist":     closes[-120:],
        "highs_hist":      highs[-120:],
        "lows_hist":       lows[-120:],
        "volumes_hist":    volumes[-120:] if volumes else [],
        **pred,
    }
