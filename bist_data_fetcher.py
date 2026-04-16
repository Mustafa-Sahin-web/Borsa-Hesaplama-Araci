"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        BIST VERİ ÇEKME MODÜLÜ  V2.0                                        ║
║                                                                              ║
║  ÖZELLİKLER:                                                                ║
║    • Yahoo Finance OHLCV çekme (önbellekli)                                ║
║    • Paralel çoklu sembol çekme (ThreadPoolExecutor)                        ║
║    • Otomatik yeniden deneme & rate-limit yönetimi                          ║
║    • Aşırı değer (outlier) filtresi                                         ║
║    • OHLCV tutarlılık doğrulaması                                           ║
║    • Benchmark (BIST100) yükleme                                            ║
║    • Sembol listesi güncelleme & doğrulama  (YENİ)                         ║
║    • Proxy desteği  (YENİ)                                                  ║
║    • Alternatif kaynak yedek  (YENİ)                                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

Kullanım:
    from bist_data_fetcher import DataFetcher
    fetcher = DataFetcher()
    closes, volumes, highs, lows, opens = fetcher.fetch("GARAN")
"""

import math
import time
import threading
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# SABİTLER
# ══════════════════════════════════════════════════════════════════════════════

BENCHMARK_TICKERS = ["XU100.IS", "^XU100", "XU100"]
MAX_WORKERS       = 12
CACHE_TTL         = 300   # saniye
CACHE_MAX_ITEMS   = 400
MIN_BARS          = 80

# BIST hisse listesi
SYMBOLS = list(dict.fromkeys([
    "AKBNK","ASELS","BIMAS","EKGYO","EREGL","FROTO","GARAN","HEKTS",
    "ISCTR","KCHOL","KRDMD","PETKM","PGSUS","SAHOL","SISE","SOKM",
    "TAVHL","TCELL","THYAO","TOASO","TUPRS","VESTL","YKBNK","ALARK",
    "ARCLK","CCOLA","DOAS","ENJSA","ENKAI","GUBRF","HALKB","ODAS",
    "OYAKC","QUAGR","KERVT","LOGO","SASA","KCAER","BRSAN","MAVI",
    "AEFES","AKSA","ALKIM","BERA","CIMSA","DOHOL","EGEEN","GESAN",
    "IHLGM","INDES","KARTN","KLNMA","KOZAL","NETAS","OTKAR",
    "PARSN","SELEC","SMGE","SNKRN","TSGYO","TTRAK","ULKER","VAKBN",
    # Ek BIST30 hisseleri
    "AKSEN","KOZAA","MGROS","OTOKAR","ISGYO","GLAXO","BUCIM","CEMTS",
    "KORDS","AGHOL","TRILC","EGPRO","SKBNK","TSKB","ZOREN",
]))

# Yahoo Finance isteği için User-Agent havuzu  YENİ
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_UA_INDEX = 0
_UA_LOCK  = threading.Lock()


def _next_user_agent() -> str:
    """Sırayla User-Agent döndür (basit round-robin)."""
    global _UA_INDEX
    with _UA_LOCK:
        ua = _USER_AGENTS[_UA_INDEX % len(_USER_AGENTS)]
        _UA_INDEX += 1
    return ua


# ══════════════════════════════════════════════════════════════════════════════
# VERİ ÇEKME SINIFI
# ══════════════════════════════════════════════════════════════════════════════

class DataFetcher:
    """
    Yahoo Finance'ten BIST OHLCV verisi çeken sınıf.

    Args:
        cache_ttl      : Önbellek geçerlilik süresi (saniye)
        max_workers    : Paralel çekme için maksimum iş parçacığı sayısı
        proxies        : requests.get(..., proxies=...) için proxy sözlüğü
        session        : Özel requests.Session nesnesi (opsiyonel)
    """

    def __init__(self,
                 cache_ttl: int = CACHE_TTL,
                 max_workers: int = MAX_WORKERS,
                 proxies: Optional[dict] = None,
                 session: Optional[requests.Session] = None):
        self._cache: dict = {}
        self._lock  = threading.Lock()
        self.cache_ttl   = cache_ttl
        self.max_workers = max_workers
        self.proxies     = proxies or {}
        self.session     = session or requests.Session()
        # Persist cookies/headers across requests for better reliability
        self.session.headers.update({
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://finance.yahoo.com/",
        })

    # ──────────────────────────────────────────────────────────────────────
    # Önbellek yardımcıları
    # ──────────────────────────────────────────────────────────────────────

    def _cache_get(self, key: str):
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() - entry[0] < self.cache_ttl:
                return entry[1:]   # (closes, volumes, highs, lows, opens)
        return None

    def _cache_set(self, key: str, data: tuple):
        with self._lock:
            self._cache[key] = (time.time(), *data)
            if len(self._cache) > CACHE_MAX_ITEMS:
                oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
                self._cache.pop(oldest, None)

    def cache_clear(self):
        """Tüm önbelleği temizle."""
        with self._lock:
            self._cache.clear()

    def cache_invalidate(self, ticker: str):
        """Belirli bir sembol için önbelleği geçersiz kıl."""
        key = self._normalize(ticker)
        with self._lock:
            self._cache.pop(key, None)

    @staticmethod
    def _normalize(ticker: str) -> str:
        """Sembol adını Yahoo Finance formatına çevir."""
        if ticker.startswith("^"): return ticker
        if ticker.endswith(".IS"):  return ticker
        return ticker + ".IS"

    # ──────────────────────────────────────────────────────────────────────
    # Ana çekme metodu
    # ──────────────────────────────────────────────────────────────────────

    def fetch(self,
              ticker: str,
              range_period: str = "2y",
              interval: str = "1d",
              retries: int = 3,
              force_refresh: bool = False
              ) -> tuple:
        """
        Tek sembol için OHLCV verisi çek.

        Args:
            ticker        : Hisse sembolü ("GARAN" veya "GARAN.IS")
            range_period  : Zaman aralığı ("1y","2y","5y" vb.)
            interval      : Bar aralığı ("1d","1wk","1mo")
            retries       : Başarısız istekte yeniden deneme sayısı
            force_refresh : True → önbelleği yoksay

        Returns:
            (closes, volumes, highs, lows, opens)  — hepsi float listesi
            Veri yoksa 5 adet boş liste döner.
        """
        full = self._normalize(ticker)

        if not force_refresh:
            cached = self._cache_get(full)
            if cached: return cached

        data = self._fetch_yahoo(full, range_period, interval, retries)

        # Birincil kaynak başarısız → alternatif endpoint dene  YENİ
        if not data[0]:
            data = self._fetch_yahoo_v7(full, range_period, interval)

        if data[0]:
            self._cache_set(full, data)
        return data

    def _fetch_yahoo(self,
                     ticker_full: str,
                     range_period: str,
                     interval: str,
                     retries: int) -> tuple:
        """Yahoo Finance v8 endpoint."""
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_full}"
            f"?range={range_period}&interval={interval}&includeAdjustedClose=true"
        )
        backoff = 0.5
        for attempt in range(retries):
            try:
                resp = self.session.get(
                    url,
                    headers={"User-Agent": _next_user_agent()},
                    proxies=self.proxies,
                    timeout=12
                )
                if resp.status_code == 404:
                    return [], [], [], [], []
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt == retries - 1:
                        log.warning(f"Fetch failed {ticker_full}: HTTP {resp.status_code}")
                        return [], [], [], [], []
                    time.sleep(backoff * (attempt + 1))
                    continue
                resp.raise_for_status()
                raw = resp.json()
                if not raw.get("chart", {}).get("result"):
                    return [], [], [], [], []
                return self._parse_chart(raw)
            except requests.exceptions.Timeout:
                log.warning(f"Timeout {ticker_full} attempt {attempt+1}")
                time.sleep(backoff * (attempt + 1))
            except Exception as e:
                if attempt == retries - 1:
                    log.warning(f"Fetch failed {ticker_full}: {e}")
                    return [], [], [], [], []
                time.sleep(backoff * (attempt + 1))
        return [], [], [], [], []

    def _fetch_yahoo_v7(self,
                        ticker_full: str,
                        range_period: str,
                        interval: str) -> tuple:
        """
        Yahoo Finance v7 yedek endpoint.
        Bazı semboller v8'de 404 verirken v7'de çalışır.
        """
        url = (
            f"https://query2.finance.yahoo.com/v7/finance/download/{ticker_full}"
            f"?range={range_period}&interval={interval}&events=history&includeAdjustedClose=true"
        )
        try:
            resp = self.session.get(
                url,
                headers={"User-Agent": _next_user_agent()},
                proxies=self.proxies,
                timeout=12
            )
            if resp.status_code != 200:
                return [], [], [], [], []
            return self._parse_csv(resp.text)
        except Exception as e:
            log.warning(f"v7 Fetch failed {ticker_full}: {e}")
            return [], [], [], [], []

    # ──────────────────────────────────────────────────────────────────────
    # Veri ayrıştırma yardımcıları
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_chart(data: dict) -> tuple:
        """Yahoo Finance v8 JSON yanıtını OHLCV listelerine çevir."""
        try:
            result = data["chart"]["result"][0]
            q      = result["indicators"]["quote"][0]
            adj    = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
        except (KeyError, IndexError, TypeError):
            return [], [], [], [], []

        closes_raw = adj if adj else q.get("close", [])
        volumes    = q.get("volume", [])
        highs      = q.get("high",   [])
        lows       = q.get("low",    [])
        opens      = q.get("open",   [])

        return DataFetcher._clean_ohlcv(closes_raw, volumes, highs, lows, opens)

    @staticmethod
    def _parse_csv(text: str) -> tuple:
        """
        Yahoo Finance v7 CSV yanıtını OHLCV listelerine çevir.
        Beklenen başlık: Date,Open,High,Low,Close,Adj Close,Volume
        """
        lines = text.strip().splitlines()
        if len(lines) < 2: return [], [], [], [], []
        header = [h.strip().lower() for h in lines[0].split(",")]
        try:
            ci = header.index("adj close") if "adj close" in header else header.index("close")
            oi = header.index("open")
            hi = header.index("high")
            li = header.index("low")
            vi = header.index("volume")
        except ValueError:
            return [], [], [], [], []

        closes_raw = []; volumes = []; highs = []; lows = []; opens = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(ci, oi, hi, li, vi): continue
            try:
                closes_raw.append(float(parts[ci]))
                opens.append(float(parts[oi]))
                highs.append(float(parts[hi]))
                lows.append(float(parts[li]))
                volumes.append(float(parts[vi]) if parts[vi] not in ("", "null") else 0.0)
            except (ValueError, IndexError):
                continue
        return DataFetcher._clean_ohlcv(closes_raw, volumes, highs, lows, opens)

    @staticmethod
    def _clean_ohlcv(closes_raw, volumes, highs, lows, opens,
                     outlier_pct: float = 0.60) -> tuple:
        """
        OHLCV verilerini temizle:
          - None / NaN / sıfır değerleri at
          - Aşırı fiyat sıçramalarını (outlier) filtrele
          - H/L/O tutarlılığını garantile
        """
        cc, cv, ch, cl, co = [], [], [], [], []
        prev = None
        n    = len(closes_raw)

        for i, c in enumerate(closes_raw):
            if not c or c <= 0: continue
            try:
                c = float(c)
                if math.isnan(c) or math.isinf(c): continue
            except (TypeError, ValueError):
                continue

            # Aşırı outlier filtresi
            if prev and prev > 0 and abs((c - prev) / prev) > outlier_pct:
                continue

            v = float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0
            h = float(highs[i])   if i < len(highs)   and highs[i]   else c
            l = float(lows[i])    if i < len(lows)     and lows[i]    else c
            o = float(opens[i])   if i < len(opens)    and opens[i]   else (prev if prev else c)

            try:
                if math.isnan(v): v = 0.0
                if math.isnan(h): h = c
                if math.isnan(l): l = c
                if math.isnan(o): o = c
            except TypeError:
                pass

            # OHLCV tutarlılık
            h = max(h, c, o)
            l = min(l, c, o)

            cc.append(c); cv.append(v); ch.append(h)
            cl.append(l); co.append(o)
            prev = c

        return cc, cv, ch, cl, co

    # ──────────────────────────────────────────────────────────────────────
    # Sembol doğrulama  YENİ
    # ──────────────────────────────────────────────────────────────────────

    def validate_symbol(self, ticker: str) -> bool:
        """
        Sembolün Yahoo Finance'te mevcut olduğunu doğrula.
        Yeterli veri yoksa False döner.
        """
        try:
            closes, *_ = self.fetch(ticker, range_period="3mo")
            return len(closes) >= 20
        except Exception:
            return False

    def validate_symbols(self, tickers: list) -> dict:
        """
        Sembol listesini paralel doğrula.
        Döner: {sembol: True/False}
        """
        results = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tickers))) as ex:
            future_map = {ex.submit(self.validate_symbol, t): t for t in tickers}
            for fut in as_completed(future_map):
                sym = future_map[fut]
                try:
                    results[sym] = fut.result()
                except Exception:
                    results[sym] = False
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Paralel çekme  YENİ (geliştirildi)
    # ──────────────────────────────────────────────────────────────────────

    def fetch_many(self,
                   tickers: list,
                   range_period: str = "2y",
                   interval: str = "1d",
                   progress_callback=None,
                   error_callback=None) -> dict:
        """
        Birden fazla sembol için paralel OHLCV çekme.

        Args:
            tickers          : Sembol listesi
            range_period     : Zaman aralığı
            interval         : Bar aralığı
            progress_callback: fn(completed: int, total: int, symbol: str)
            error_callback   : fn(symbol: str, exception: Exception)

        Returns:
            {sembol: (closes, volumes, highs, lows, opens)}
        """
        results  = {}
        total    = len(tickers)
        completed = 0
        lock      = threading.Lock()

        def _worker(sym):
            nonlocal completed
            try:
                data = self.fetch(sym, range_period, interval)
                with lock:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total, sym)
                return sym, data
            except Exception as e:
                with lock:
                    completed += 1
                    if error_callback:
                        error_callback(sym, e)
                    if progress_callback:
                        progress_callback(completed, total, sym)
                return sym, ([], [], [], [], [])

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(_worker, t): t for t in tickers}
            for fut in as_completed(futures):
                sym, data = fut.result()
                results[sym] = data

        return results

    # ──────────────────────────────────────────────────────────────────────
    # Benchmark yükleme
    # ──────────────────────────────────────────────────────────────────────

    def load_benchmark(self) -> list:
        """
        BIST100 benchmark kapanış fiyatlarını çek.
        Birden fazla ticker dener, ilk başarılıyı döner.
        """
        for sym in BENCHMARK_TICKERS:
            closes, *_ = self.fetch(sym)
            if len(closes) >= MIN_BARS:
                log.info(f"Benchmark yüklendi: {sym} ({len(closes)} bar)")
                return closes
        log.warning("Benchmark yüklenemedi!")
        return []

    # ──────────────────────────────────────────────────────────────────────
    # Gerçek zamanlı fiyat  YENİ
    # ──────────────────────────────────────────────────────────────────────

    def fetch_realtime_price(self, ticker: str) -> Optional[float]:
        """
        Yahoo Finance quote API'sinden anlık fiyat çek.
        Döner: float (fiyat) veya None
        """
        full = self._normalize(ticker)
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{full}?range=1d&interval=1m"
        try:
            resp = self.session.get(
                url,
                headers={"User-Agent": _next_user_agent()},
                proxies=self.proxies,
                timeout=8
            )
            if resp.status_code != 200: return None
            data   = resp.json()
            result = data["chart"]["result"][0]
            meta   = result.get("meta", {})
            price  = meta.get("regularMarketPrice") or meta.get("previousClose")
            return float(price) if price else None
        except Exception as e:
            log.warning(f"Realtime price failed {full}: {e}")
            return None

    def fetch_realtime_prices(self, tickers: list) -> dict:
        """
        Birden fazla sembol için anlık fiyat çek.
        Döner: {sembol: fiyat_float_veya_None}
        """
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_map = {ex.submit(self.fetch_realtime_price, t): t for t in tickers}
            for fut in as_completed(future_map):
                sym = future_map[fut]
                try:
                    results[sym] = fut.result()
                except Exception:
                    results[sym] = None
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Çoklu zaman dilimi çekme  YENİ
    # ──────────────────────────────────────────────────────────────────────

    def fetch_multi_timeframe(self, ticker: str) -> dict:
        """
        Bir sembol için birden fazla zaman diliminde veri çek.
        Döner: {"1d": (ohlcv...), "1wk": (ohlcv...), "1mo": (ohlcv...)}
        """
        tf_map = {
            "1d":  ("2y",  "1d"),
            "1wk": ("5y",  "1wk"),
            "1mo": ("10y", "1mo"),
        }
        results = {}
        for label, (rng, ivl) in tf_map.items():
            data = self.fetch(ticker, range_period=rng, interval=ivl)
            if data[0]:
                results[label] = data
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Önbellek istatistikleri  YENİ
    # ──────────────────────────────────────────────────────────────────────

    def cache_stats(self) -> dict:
        """Önbellek durumu hakkında istatistik döndür."""
        with self._lock:
            now    = time.time()
            total  = len(self._cache)
            fresh  = sum(1 for v in self._cache.values() if now - v[0] < self.cache_ttl)
            stale  = total - fresh
            oldest = min((v[0] for v in self._cache.values()), default=now)
        return {
            "total":   total,
            "fresh":   fresh,
            "stale":   stale,
            "oldest_age_sec": round(now - oldest, 1) if total else 0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# MODÜL DÜZEYİ KULLANIM KOLAYLIĞI  (geriye dönük uyumluluk)
# ══════════════════════════════════════════════════════════════════════════════

_default_fetcher = DataFetcher()


def fetch_ohlcv(ticker: str, range_period: str = "2y",
                interval: str = "1d", retries: int = 3) -> tuple:
    """
    Geriye dönük uyumluluk için modül düzeyi fonksiyon.
    Varsayılan DataFetcher örneğini kullanır.
    """
    return _default_fetcher.fetch(ticker, range_period, interval, retries)


def load_benchmark() -> list:
    """Geriye dönük uyumluluk için modül düzeyi fonksiyon."""
    return _default_fetcher.load_benchmark()
