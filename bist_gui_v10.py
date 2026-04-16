"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       BIST STRATEJİK TARAYICI  V10  —  Tkinter GUI                        ║
║                                                                              ║
║  Modüler yapı:                                                              ║
║    bist_data_fetcher.py   → Veri çekme                                     ║
║    bist_analysis_engine.py → Hesaplama & puanlama                          ║
║                                                                              ║
║  GUI'de yeni özellikler:                                                    ║
║    • Yeni indikatörler paneli: MFI, Supertrend, Vortex, Ichimoku, HMA      ║
║    • RSI Diverjansı gösterimi                                               ║
║    • Gerçek zamanlı fiyat yenileme butonu                                  ║
║    • Sembol doğrulama (özel sembol eklerken)                               ║
║    • Önbellek durumu göstergesi                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
Gereksinimler:
    pip install requests
Çalıştır:
    python bist_gui_v10.py
"""

import math, time, threading, logging, csv, os, tkinter as tk
from tkinter import ttk, messagebox, filedialog
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from bist_data_fetcher    import DataFetcher, SYMBOLS
from bist_analysis_engine import (
    analyze, action_bucket, TIMEFRAME_CONFIG,
    detect_candlestick_patterns,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# RENKLER & STİL
# ══════════════════════════════════════════════════════════════════════════════
BG      = "#0d1117"; BG2 = "#161b22"; BG3 = "#21262d"; BG4 = "#2d333b"
BORDER  = "#30363d"; FG  = "#e6edf3"; FG2 = "#8b949e"; FG3 = "#6e7681"
GREEN   = "#3fb950"; GREEN2 = "#238636"; GREEN3 = "#1a7f37"
RED     = "#f85149"; RED2   = "#da3633"
YELLOW  = "#d29922"; YELLOW2= "#e3b341"
BLUE    = "#58a6ff"; BLUE2  = "#1f6feb"
PURPLE  = "#bc8cff"; ORANGE = "#ffa657"; CYAN = "#39d353"
TEAL    = "#56d364"; PINK   = "#ff7b72"

SCORE_COLORS = {
    (8.5, 10):  GREEN,
    (7.0, 8.5): CYAN,
    (5.5, 7.0): YELLOW,
    (3.5, 5.5): ORANGE,
    (0.0, 3.5): RED,
}

def score_color(s):
    for (lo, hi), c in SCORE_COLORS.items():
        if lo <= s <= hi: return c
    return FG

def aksiyon_color(a):
    if "GÜÇLÜ AL" in a or "KESİN AL" in a: return GREEN
    if "✅" in a or "🍀" in a or "AL" in a: return CYAN
    if "BEKLE" in a or "NÖTR" in a or "İZLE" in a: return YELLOW
    if "SAT" in a or "ÇIKIŞ" in a:         return RED
    if "AŞIRI" in a:                       return ORANGE
    return FG2

APP_VERSION = "V10.0"
MAX_WORKERS = 12

# ══════════════════════════════════════════════════════════════════════════════
# GELİŞMİŞ FİYAT GRAFİĞİ
# ══════════════════════════════════════════════════════════════════════════════
def draw_price_chart(canvas, closes, highs, lows, volumes, target, stop_val,
                     bb_upper=None, bb_lower=None, fib_levels=None,
                     width=560, height=240):
    canvas.delete("all")
    if not closes or len(closes) < 5: return
    n   = min(80, len(closes))
    c   = closes[-n:]; h = highs[-n:]; l = lows[-n:]
    vol = volumes[-n:] if volumes else []

    vol_h   = int(height * 0.20) if vol else 0
    price_h = height - vol_h
    pad_l=8; pad_r=52; pad_t=15; pad_b=22

    all_vals = [*h, *l, target, stop_val]
    if bb_upper: all_vals.append(bb_upper)
    if bb_lower: all_vals.append(bb_lower)
    mn = min(all_vals) * 0.995; mx = max(all_vals) * 1.005
    rng = mx - mn if mx != mn else 1
    cw = width - pad_l - pad_r
    ch = price_h - pad_t - pad_b

    def yt(v): return pad_t + ch * (1 - (v - mn) / rng)
    def xc(i): return pad_l + int((i + 0.5) * cw / n)

    for pct in [0.2, 0.4, 0.6, 0.8]:
        yy = pad_t + ch * pct
        canvas.create_line(pad_l, yy, width - pad_r, yy, fill=BG4, dash=(2, 5))

    if fib_levels:
        fib_colors = {"38.2": "#4a4a8a", "50.0": "#4a6a8a",
                      "61.8": "#2a5a6a", "78.6": "#2a4a5a"}
        for level_key, color in fib_colors.items():
            level_v = fib_levels.get(level_key)
            if level_v and mn <= level_v <= mx:
                yy = yt(level_v)
                canvas.create_line(pad_l, yy, width - pad_r, yy,
                                   fill=color, dash=(3, 6))
                canvas.create_text(width - pad_r + 2, yy,
                                   text=f"F{level_key}", fill=color,
                                   font=("Consolas", 6), anchor="w")

    if bb_upper and bb_lower and mn <= bb_upper <= mx * 1.1 and mn * 0.9 <= bb_lower <= mx:
        canvas.create_line(pad_l, yt(bb_upper), width - pad_r, yt(bb_upper),
                           fill="#3a4a6a", dash=(4, 4))
        canvas.create_line(pad_l, yt(bb_lower), width - pad_r, yt(bb_lower),
                           fill="#3a4a6a", dash=(4, 4))

    canvas.create_line(pad_l, yt(target), width - pad_r, yt(target),
                       fill=GREEN, dash=(5, 3), width=1)
    canvas.create_text(width - pad_r + 2, yt(target),
                       text=f"▶ {target:.0f}", fill=GREEN,
                       font=("Consolas", 7), anchor="w")
    canvas.create_line(pad_l, yt(stop_val), width - pad_r, yt(stop_val),
                       fill=RED, dash=(5, 3), width=1)
    canvas.create_text(width - pad_r + 2, yt(stop_val),
                       text=f"▼ {stop_val:.0f}", fill=RED,
                       font=("Consolas", 7), anchor="w")

    pts = [pad_l, yt(c[0])]
    for i, v in enumerate(c): pts += [xc(i), yt(v)]
    pts += [xc(n - 1), price_h - pad_b, pad_l, price_h - pad_b]
    canvas.create_polygon(*pts, fill="#1a3a28", outline="")

    line_pts = []
    for i, v in enumerate(c): line_pts += [xc(i), yt(v)]
    canvas.create_line(*line_pts, fill=GREEN, width=1.8, smooth=True)
    canvas.create_oval(xc(n-1)-4, yt(c[-1])-4, xc(n-1)+4, yt(c[-1])+4,
                       fill=GREEN, outline=BG)

    canvas.create_text(pad_l, pad_t, text=f"{mx:.1f}", fill=FG3,
                       font=("Consolas", 7), anchor="nw")
    canvas.create_text(pad_l, price_h - pad_b, text=f"{mn:.1f}", fill=FG3,
                       font=("Consolas", 7), anchor="sw")
    canvas.create_text(width // 2, height - 5, text=f"Son {n} gün",
                       fill=FG3, font=("Consolas", 7))

    if vol and vol_h > 0:
        max_v  = max(vol) or 1
        base_y = height - 4
        bar_h2 = vol_h - 6
        for i, v in enumerate(vol):
            bh = int(bar_h2 * v / max_v)
            x  = xc(i); bw = max(1, cw // n - 1)
            clr = "#1a4a2a" if i > 0 and c[i] >= c[i-1] else "#4a1a1a"
            if bh > 0:
                canvas.create_rectangle(x - bw//2, base_y - bh,
                                        x + bw//2, base_y,
                                        fill=clr, outline="")

# ══════════════════════════════════════════════════════════════════════════════
# ANA GUI
# ══════════════════════════════════════════════════════════════════════════════
class BISTApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"📈  BIST Stratejik Tarayıcı {APP_VERSION}")
        self.configure(bg=BG)
        self.geometry("1400x900")
        self.minsize(1150, 740)

        self.fetcher      = DataFetcher()
        self.benchmark    = []
        self.rapor        = []
        self.scan_running = False
        self.watchlist    = []

        self._setup_styles()
        self._build_ui()
        threading.Thread(target=self._load_benchmark_bg, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════
    # STİLLER
    # ══════════════════════════════════════════════════════════════════════
    def _setup_styles(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=BG2, foreground=FG2,
                     padding=[16, 7], font=("Segoe UI", 10))
        st.map("TNotebook.Tab",
               background=[("selected", BG3)], foreground=[("selected", FG)])
        st.configure("Treeview", background=BG2, fieldbackground=BG2,
                     foreground=FG, rowheight=28, font=("Consolas", 10), borderwidth=0)
        st.configure("Treeview.Heading", background=BG3, foreground=BLUE,
                     font=("Segoe UI", 10, "bold"), relief="flat")
        st.map("Treeview", background=[("selected", BLUE2)],
               foreground=[("selected", FG)])
        st.configure("TScrollbar", background=BG3, troughcolor=BG,
                     borderwidth=0, arrowcolor=FG2)
        st.configure("TProgressbar", background=GREEN2, troughcolor=BG3, borderwidth=0)
        st.configure("TCombobox", fieldbackground=BG3, background=BG3,
                     foreground=FG, selectbackground=BLUE2)

    # ══════════════════════════════════════════════════════════════════════
    # ANA UI
    # ══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        topbar = tk.Frame(self, bg=BG2, height=52)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)
        tk.Label(topbar, text=f"📈  BIST STRATEJİK TARAYICI  {APP_VERSION}",
                 bg=BG2, fg=BLUE, font=("Segoe UI", 14, "bold")
                 ).pack(side="left", padx=18, pady=8)
        self.lbl_time = tk.Label(topbar, text="", bg=BG2, fg=FG2,
                                 font=("Consolas", 10))
        self.lbl_time.pack(side="right", padx=18)
        self._tick_clock()
        self.lbl_bm = tk.Label(topbar, text="⏳ Benchmark yükleniyor…",
                               bg=BG2, fg=YELLOW, font=("Consolas", 9))
        self.lbl_bm.pack(side="right", padx=10)
        # Önbellek durumu  YENİ
        self.lbl_cache = tk.Label(topbar, text="", bg=BG2, fg=FG3,
                                  font=("Consolas", 8))
        self.lbl_cache.pack(side="right", padx=6)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._build_scan_tab()
        self._build_detail_tab()
        self._build_watchlist_tab()
        self._build_market_tab()
        self.after(10000, self._update_cache_label)

    # ══════════════════════════════════════════════════════════════════════
    # SEKME 1 — TARAMA
    # ══════════════════════════════════════════════════════════════════════
    def _build_scan_tab(self):
        frm = tk.Frame(self.nb, bg=BG)
        self.nb.add(frm, text="  🔍  Tarama  ")

        ctrl = tk.Frame(frm, bg=BG2, height=52)
        ctrl.pack(fill="x")
        ctrl.pack_propagate(False)

        self.btn_scan = tk.Button(
            ctrl, text="▶  Taramayı Başlat", bg=GREEN3, fg="white",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=6,
            cursor="hand2", activebackground=GREEN2, command=self._start_scan)
        self.btn_scan.pack(side="left", padx=12, pady=8)

        tk.Button(ctrl, text="🗑 Önbelleği Temizle", bg=BG3, fg=FG,      # YENİ
                  font=("Segoe UI", 9), relief="flat", padx=8, pady=4,
                  cursor="hand2", command=self._clear_cache
                  ).pack(side="left", padx=4, pady=10)

        self.btn_export = tk.Button(
            ctrl, text="💾 CSV", bg=BG3, fg=FG,
            font=("Segoe UI", 9), relief="flat", padx=8, pady=4,
            cursor="hand2", command=self._export_csv)
        self.btn_export.pack(side="left", padx=4, pady=10)

        self.lbl_progress = tk.Label(ctrl, text="Hazır", bg=BG2, fg=FG2,
                                     font=("Consolas", 9))
        self.lbl_progress.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(ctrl, orient="horizontal",
                                        length=220, mode="determinate")
        self.progress.pack(side="left", padx=4, pady=14)

        self.filter_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrl, text="Sadece AL", variable=self.filter_var,
                       bg=BG2, fg=FG2, selectcolor=BG3, activebackground=BG2,
                       activeforeground=FG, font=("Segoe UI", 9),
                       command=self._refresh_table).pack(side="left", padx=8)

        tk.Label(ctrl, text="Sırala:", bg=BG2, fg=FG2,
                 font=("Segoe UI", 9)).pack(side="right", padx=4)
        self.sort_var = tk.StringVar(value="Puan")
        sort_opts = ["Puan", "RSI", "Beklenen %", "Risk/Ödül", "Güven", "ADX", "MFI"]  # YENİ: MFI
        sort_menu = ttk.Combobox(ctrl, textvariable=self.sort_var,
                                 values=sort_opts, width=12, state="readonly")
        sort_menu.pack(side="right", padx=8, pady=12)
        sort_menu.bind("<<ComboboxSelected>>", lambda e: self._refresh_table())

        cols = ("Hisse", "Fiyat", "RSI", "Puan", "Aksiyon",
                "Hedef", "Stop", "Bek%", "R/R", "Güven", "ADX",
                "Supertrend", "Formasyon")    # YENİ: Supertrend sütunu
        self.tree = ttk.Treeview(frm, columns=cols, show="headings",
                                 selectmode="browse")
        widths = {"Hisse": 75, "Fiyat": 90, "RSI": 55, "Puan": 60,
                  "Aksiyon": 140, "Hedef": 90, "Stop": 85, "Bek%": 65,
                  "R/R": 55, "Güven": 65, "ADX": 55, "Supertrend": 80,
                  "Formasyon": 160}
        for col in cols:
            self.tree.heading(col, text=col,
                              command=lambda _c=col: self._sort_by(_c))
            self.tree.column(col, width=widths.get(col, 80), anchor="center")

        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        for tag, clr in [("buy_strong", GREEN), ("buy", CYAN),
                          ("wait", YELLOW), ("sell", RED), ("neutral", FG2)]:
            self.tree.tag_configure(tag, foreground=clr)

        self.tree.bind("<Double-1>",        self._on_row_double)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

    # ══════════════════════════════════════════════════════════════════════
    # SEKME 2 — DETAY ANALİZ
    # ══════════════════════════════════════════════════════════════════════
    def _build_detail_tab(self):
        frm = tk.Frame(self.nb, bg=BG)
        self.nb.add(frm, text="  📊  Analiz  ")

        search_frm = tk.Frame(frm, bg=BG2, height=52)
        search_frm.pack(fill="x")
        search_frm.pack_propagate(False)
        tk.Label(search_frm, text="Hisse Kodu:", bg=BG2, fg=FG2,
                 font=("Segoe UI", 10)).pack(side="left", padx=14, pady=12)
        self.entry_sym = tk.Entry(search_frm, bg=BG3, fg=FG, insertbackground=FG,
                                   font=("Consolas", 12, "bold"), relief="flat", width=10)
        self.entry_sym.pack(side="left", ipady=5)
        self.entry_sym.bind("<Return>", lambda e: self._analyze_single())
        tk.Button(search_frm, text="Analiz Et", bg=BLUE2, fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12,
                  cursor="hand2", command=self._analyze_single
                  ).pack(side="left", padx=8, pady=10)
        # Anlık fiyat yenile butonu  YENİ
        tk.Button(search_frm, text="🔄 Fiyat Yenile", bg=BG3, fg=FG,
                  font=("Segoe UI", 9), relief="flat", padx=8,
                  cursor="hand2", command=self._refresh_realtime_price
                  ).pack(side="left", padx=4, pady=10)
        self.lbl_analyzing = tk.Label(search_frm, text="", bg=BG2, fg=YELLOW,
                                      font=("Consolas", 9))
        self.lbl_analyzing.pack(side="left", padx=8)
        self.lbl_realtime = tk.Label(search_frm, text="", bg=BG2, fg=CYAN,   # YENİ
                                     font=("Consolas", 9))
        self.lbl_realtime.pack(side="left", padx=8)

        body = tk.Frame(frm, bg=BG)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG, width=360)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.lbl_hisse_title = tk.Label(left, text="—", bg=BG, fg=BLUE,
                                         font=("Segoe UI", 22, "bold"))
        self.lbl_hisse_title.pack(pady=(16, 2), padx=16, anchor="w")
        self.lbl_aksiyon = tk.Label(left, text="", bg=BG, fg=GREEN,
                                    font=("Segoe UI", 12, "bold"))
        self.lbl_aksiyon.pack(padx=16, anchor="w")
        self.lbl_pattern = tk.Label(left, text="", bg=BG, fg=PURPLE,
                                     font=("Segoe UI", 9))
        self.lbl_pattern.pack(padx=16, anchor="w")
        # RSI diverjansı etiketi  YENİ
        self.lbl_divergence = tk.Label(left, text="", bg=BG, fg=ORANGE,
                                        font=("Segoe UI", 9, "bold"))
        self.lbl_divergence.pack(padx=16, anchor="w")

        self.metrics_frm = tk.Frame(left, bg=BG)
        self.metrics_frm.pack(fill="x", padx=12, pady=6)

        note_outer = tk.Frame(left, bg=BG2)
        note_outer.pack(fill="both", expand=True, padx=10, pady=6)
        tk.Label(note_outer, text="📝  Analiz Notu", bg=BG2, fg=FG2,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=(6, 2))
        self.txt_note = tk.Text(note_outer, bg=BG2, fg=FG, font=("Consolas", 9),
                                relief="flat", wrap="word", height=9,
                                state="disabled", selectbackground=BLUE2)
        self.txt_note.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        chart_frm = tk.Frame(right, bg=BG2)
        chart_frm.pack(fill="x", padx=10, pady=(10, 4))
        hdr_frm = tk.Frame(chart_frm, bg=BG2)
        hdr_frm.pack(fill="x")
        tk.Label(hdr_frm, text="  📈 Fiyat & Hacim Grafiği (Son 80 Gün)",
                 bg=BG2, fg=FG2, font=("Segoe UI", 9)
                 ).pack(side="left", pady=(4, 0))
        tk.Label(hdr_frm, text="─── Fiyat  ─ ─ Hedef/Stop  ─ ─ Bollinger  ── Fibonacci",
                 bg=BG2, fg=FG3, font=("Consolas", 7)
                 ).pack(side="right", padx=8, pady=(4, 0))
        self.chart_canvas = tk.Canvas(chart_frm, bg=BG2, height=240,
                                      highlightthickness=0)
        self.chart_canvas.pack(fill="x", padx=8, pady=(2, 8))

        ind_outer = tk.Frame(right, bg=BG2)
        ind_outer.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(ind_outer, text="  🔬 İndikatörler", bg=BG2, fg=FG2,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 0))
        self.ind_frm = tk.Frame(ind_outer, bg=BG2)
        self.ind_frm.pack(fill="x", padx=8, pady=(2, 8))

        # Yeni indikatörler satırı  YENİ
        ind2_outer = tk.Frame(right, bg=BG3)
        ind2_outer.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(ind2_outer, text="  🆕 Gelişmiş İndikatörler",
                 bg=BG3, fg=FG2, font=("Segoe UI", 9, "bold")
                 ).pack(anchor="w", pady=(4, 0))
        self.ind2_frm = tk.Frame(ind2_outer, bg=BG3)
        self.ind2_frm.pack(fill="x", padx=8, pady=(2, 8))

        tf_frm = tk.Frame(right, bg=BG)
        tf_frm.pack(fill="both", expand=True, padx=10, pady=4)
        tk.Label(tf_frm, text="⏱  Zaman Dilimi Analizi", bg=BG, fg=FG2,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        tf_cols = ("TF", "Durum", "Puan", "Değişim%", "RSI",
                   "MACD", "Stoch-K", "ADX", "Güven%", "Risk")
        self.tf_tree = ttk.Treeview(tf_frm, columns=tf_cols, show="headings",
                                    height=7, selectmode="none")
        tf_widths = {"TF": 42, "Durum": 130, "Puan": 65, "Değişim%": 80,
                     "RSI": 55, "MACD": 70, "Stoch-K": 70, "ADX": 55,
                     "Güven%": 65, "Risk": 65}
        for col in tf_cols:
            self.tf_tree.heading(col, text=col)
            self.tf_tree.column(col, width=tf_widths.get(col, 70), anchor="center")
        tf_sb = ttk.Scrollbar(tf_frm, orient="vertical",
                              command=self.tf_tree.yview)
        self.tf_tree.configure(yscrollcommand=tf_sb.set)
        tf_sb.pack(side="right", fill="y")
        self.tf_tree.pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════════════
    # SEKME 3 — İZLEME LİSTESİ
    # ══════════════════════════════════════════════════════════════════════
    def _build_watchlist_tab(self):
        frm = tk.Frame(self.nb, bg=BG)
        self.nb.add(frm, text="  ⭐  İzleme  ")

        bar = tk.Frame(frm, bg=BG2, height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="Hisse Ekle:", bg=BG2, fg=FG2,
                 font=("Segoe UI", 10)).pack(side="left", padx=14, pady=12)
        self.entry_wl = tk.Entry(bar, bg=BG3, fg=FG, insertbackground=FG,
                                  font=("Consolas", 12), relief="flat", width=10)
        self.entry_wl.pack(side="left", ipady=4)
        self.entry_wl.bind("<Return>", lambda e: self._wl_add())
        for text, bg_c, cmd in [
            ("+ Ekle",    GREEN3, self._wl_add),
            ("Sil",       RED2,   self._wl_remove),
            ("↻ Güncelle", BG3,   self._wl_refresh),
        ]:
            tk.Button(bar, text=text, bg=bg_c,
                      fg="white" if bg_c != BG3 else FG,
                      font=("Segoe UI", 10), relief="flat", padx=10,
                      cursor="hand2", command=cmd).pack(side="left", padx=4, pady=10)

        cols = ("Hisse", "Fiyat", "RSI", "Puan", "Aksiyon",
                "Hedef", "Stop", "Bek%", "TF Uyum", "Supertrend")  # YENİ
        self.wl_tree = ttk.Treeview(frm, columns=cols, show="headings",
                                    selectmode="browse")
        wl_w = {"Hisse": 75, "Fiyat": 90, "RSI": 60, "Puan": 65,
                "Aksiyon": 150, "Hedef": 90, "Stop": 85,
                "Bek%": 70, "TF Uyum": 80, "Supertrend": 90}
        for col in cols:
            self.wl_tree.heading(col, text=col)
            self.wl_tree.column(col, width=wl_w.get(col, 80), anchor="center")
        for tag, clr in [("buy_strong", GREEN), ("buy", CYAN),
                          ("wait", YELLOW), ("sell", RED), ("neutral", FG2)]:
            self.wl_tree.tag_configure(tag, foreground=clr)
        wl_sb = ttk.Scrollbar(frm, orient="vertical", command=self.wl_tree.yview)
        self.wl_tree.configure(yscrollcommand=wl_sb.set)
        wl_sb.pack(side="right", fill="y")
        self.wl_tree.pack(fill="both", expand=True)
        self.wl_tree.bind("<Double-1>", self._wl_double)

    # ══════════════════════════════════════════════════════════════════════
    # SEKME 4 — PİYASA ÖZETİ
    # ══════════════════════════════════════════════════════════════════════
    def _build_market_tab(self):
        frm = tk.Frame(self.nb, bg=BG)
        self.nb.add(frm, text="  📋  Piyasa Özeti  ")

        top = tk.Frame(frm, bg=BG2, height=52)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Button(top, text="↻ Özeti Güncelle", bg=BG3, fg=FG,
                  font=("Segoe UI", 10), relief="flat", padx=12,
                  cursor="hand2", command=self._update_market_summary
                  ).pack(side="left", padx=12, pady=12)
        self.lbl_mkt_status = tk.Label(
            top, text="Tarama tamamlandığında otomatik güncellenir.",
            bg=BG2, fg=FG3, font=("Consolas", 9))
        self.lbl_mkt_status.pack(side="left", padx=8)

        cards_frm = tk.Frame(frm, bg=BG)
        cards_frm.pack(fill="x", padx=16, pady=14)
        self.mkt_cards = {}
        card_defs = [
            ("total",    "Toplam Hisse", "—", FG),
            ("buy_cnt",  "AL Sinyali",   "—", GREEN),
            ("sell_cnt", "SAT Sinyali",  "—", RED),
            ("wait_cnt", "İZLE",         "—", YELLOW),
            ("avg_puan", "Ort. Puan",    "—", BLUE),
            ("avg_rsi",  "Ort. RSI",     "—", CYAN),
            ("top_hisse","En İyi Hisse", "—", GREEN),
            ("bottom_h", "En Zayıf",    "—", RED),
        ]
        for i, (key, label, val, clr) in enumerate(card_defs):
            card = tk.Frame(cards_frm, bg=BG3, padx=14, pady=10)
            card.grid(row=i // 4, column=i % 4, padx=6, pady=6, sticky="ew")
            cards_frm.columnconfigure(i % 4, weight=1)
            tk.Label(card, text=label, bg=BG3, fg=FG2,
                     font=("Segoe UI", 9)).pack(anchor="w")
            lbl = tk.Label(card, text=val, bg=BG3, fg=clr,
                           font=("Consolas", 14, "bold"))
            lbl.pack(anchor="w")
            self.mkt_cards[key] = lbl

        tk.Label(frm, text="  🏆 Top 10 Hisse (Puana Göre)",
                 bg=BG, fg=FG2, font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w", padx=16, pady=(8, 2))
        top10_cols = ("Sıra", "Hisse", "Puan", "Aksiyon",
                      "Bek%", "R/R", "Supertrend", "Formasyon")  # YENİ
        self.top10_tree = ttk.Treeview(frm, columns=top10_cols,
                                       show="headings", height=10)
        top10_w = {"Sıra": 40, "Hisse": 80, "Puan": 70, "Aksiyon": 150,
                   "Bek%": 80, "R/R": 70, "Supertrend": 90, "Formasyon": 200}
        for col in top10_cols:
            self.top10_tree.heading(col, text=col)
            self.top10_tree.column(col, width=top10_w.get(col, 90), anchor="center")
        for tag, clr in [("buy_strong", GREEN), ("buy", CYAN),
                          ("wait", YELLOW), ("sell", RED), ("neutral", FG2)]:
            self.top10_tree.tag_configure(tag, foreground=clr)
        t10sb = ttk.Scrollbar(frm, orient="vertical",
                              command=self.top10_tree.yview)
        self.top10_tree.configure(yscrollcommand=t10sb.set)
        t10sb.pack(side="right", fill="y", padx=(0, 2))
        self.top10_tree.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.top10_tree.bind("<Double-1>", self._top10_double)

    # ══════════════════════════════════════════════════════════════════════
    # ARKA PLAN & TARAMA
    # ══════════════════════════════════════════════════════════════════════
    def _load_benchmark_bg(self):
        self.benchmark = self.fetcher.load_benchmark()
        if self.benchmark:
            self.after(0, lambda: self.lbl_bm.config(
                text=f"✅ Benchmark hazır ({len(self.benchmark)} bar)", fg=GREEN))
        else:
            self.after(0, lambda: self.lbl_bm.config(
                text="⚠️  Benchmark yok", fg=YELLOW))

    def _start_scan(self):
        if self.scan_running: return
        self.scan_running = True
        self.btn_scan.config(state="disabled", text="⏳ Taranıyor…")
        self.rapor = []
        for row in self.tree.get_children(): self.tree.delete(row)
        self.progress["value"] = 0
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        """Paralel tarama: veri çekme + analiz ayrı katmanlarla."""
        total = len(SYMBOLS); done = 0

        def _process(sym):
            closes, volumes, highs, lows, opens = self.fetcher.fetch(sym)
            if len(closes) < 80:
                return None
            return analyze(sym, closes, volumes, highs, lows, opens, self.benchmark)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_process, sym): sym for sym in SYMBOLS}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res:
                        self.rapor.append(res)
                        self.after(0, lambda r=res: self._add_row(r))
                except Exception as e:
                    log.warning(f"Scan error: {e}")
                done += 1
                pct = done / total * 100
                self.after(0, lambda p=pct, d=done, t=total: (
                    self.progress.__setitem__("value", p),
                    self.lbl_progress.config(text=f"{d}/{t} hisse")
                ))
        self.after(0, self._scan_done)

    def _scan_done(self):
        self.scan_running = False
        self.btn_scan.config(state="normal", text="▶  Taramayı Başlat")
        self.lbl_progress.config(
            text=f"✅  {len(self.rapor)} hisse tamamlandı — "
                 f"{datetime.now().strftime('%H:%M:%S')}")
        self._refresh_table()
        self.after(0, self._update_market_summary)

    def _add_row(self, r):
        tag  = self._tag(r["aksiyon"])
        st   = "▲ Yukarı" if r.get("supertrend_dir", 1) == 1 else "▼ Aşağı"
        st_c = "buy" if r.get("supertrend_dir", 1) == 1 else "sell"
        self.tree.insert("", tk.END, values=(
            r["hisse"], f"{r['fiyat']:.2f}", f"{r['rsi']:.1f}",
            f"{r['puan']:.1f}", r["aksiyon"],
            f"{r['hedef']:.2f}", f"{r['stop']:.2f}",
            f"{r['bek_get']:+.1f}%", f"{r['rr']:.2f}x",
            f"%{r['guven_skoru']}", f"{r.get('adx',0):.1f}",
            st, r.get("pattern", "")
        ), tags=(tag,))

    def _refresh_table(self):
        for row in self.tree.get_children(): self.tree.delete(row)
        key_map = {
            "Puan": "puan", "RSI": "rsi",
            "Beklenen %": "bek_get", "Risk/Ödül": "rr",
            "Güven": "guven_skoru", "ADX": "adx", "MFI": "mfi",
        }
        key   = key_map.get(self.sort_var.get(), "puan")
        rapor = self.rapor
        if self.filter_var.get():
            rapor = [r for r in rapor if action_bucket(r.get("aksiyon", "")) == "buy"]
        for r in sorted(rapor, key=lambda x: x.get(key, 0), reverse=True):
            self._add_row(r)

    def _tag(self, aksiyon):
        a      = (aksiyon or "").upper()
        bucket = action_bucket(aksiyon)
        if "GÜÇLÜ AL" in a or "KESİN AL" in a: return "buy_strong"
        if bucket == "buy":                     return "buy"
        if bucket in ("wait", "overbought"):    return "wait"
        if bucket == "sell":                    return "sell"
        return "neutral"

    def _sort_by(self, col):
        col_map = {
            "Puan": "puan", "RSI": "rsi", "Fiyat": "fiyat",
            "Bek%": "bek_get", "R/R": "rr",
            "Güven": "guven_skoru", "ADX": "adx",
        }
        key = col_map.get(col)
        if not key: return
        self.rapor.sort(key=lambda x: x.get(key, 0), reverse=True)
        self._refresh_table()

    # ══════════════════════════════════════════════════════════════════════
    # SATIR SEÇİMİ
    # ══════════════════════════════════════════════════════════════════════
    def _on_row_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0], "values")
        if vals:
            self.entry_sym.delete(0, tk.END)
            self.entry_sym.insert(0, vals[0])

    def _on_row_double(self, event):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0], "values")
        if not vals: return
        sym    = vals[0]
        cached = next((r for r in self.rapor if r["hisse"] == sym), None)
        if cached:
            self.nb.select(1)
            self._show_detail(cached)

    # ══════════════════════════════════════════════════════════════════════
    # TEK HİSSE ANALİZİ
    # ══════════════════════════════════════════════════════════════════════
    def _analyze_single(self):
        sym = self.entry_sym.get().strip().upper()
        if not sym: return
        cached = next((r for r in self.rapor if r["hisse"] == sym), None)
        if cached:
            self._show_detail(cached); return
        self.lbl_analyzing.config(text=f"⏳ {sym} indiriliyor…", fg=YELLOW)
        threading.Thread(target=self._analyze_worker, args=(sym,), daemon=True).start()

    def _analyze_worker(self, sym):
        closes, volumes, highs, lows, opens = self.fetcher.fetch(sym)
        res = analyze(sym, closes, volumes, highs, lows, opens, self.benchmark)
        if res:
            self.after(0, lambda: self._show_detail(res))
            self.after(0, lambda: self.lbl_analyzing.config(text="", fg=FG))
        else:
            self.after(0, lambda: self.lbl_analyzing.config(
                text=f"❌ '{sym}' bulunamadı veya veri yetersiz", fg=RED))

    # YENİ: Anlık fiyat yenile
    def _refresh_realtime_price(self):
        sym = self.entry_sym.get().strip().upper()
        if not sym: return
        self.lbl_realtime.config(text="⏳ Fiyat yükleniyor…", fg=YELLOW)
        def _worker():
            price = self.fetcher.fetch_realtime_price(sym)
            if price:
                self.after(0, lambda p=price: self.lbl_realtime.config(
                    text=f"Anlık: {p:.2f} TL", fg=CYAN))
            else:
                self.after(0, lambda: self.lbl_realtime.config(
                    text="Fiyat alınamadı", fg=RED))
        threading.Thread(target=_worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════
    # DETAY GÖSTERME
    # ══════════════════════════════════════════════════════════════════════
    def _show_detail(self, r):
        self.lbl_hisse_title.config(text=f"  {r['hisse']}")
        self.lbl_aksiyon.config(text=f"  {r['aksiyon']}",
                                fg=aksiyon_color(r["aksiyon"]))
        pattern = r.get("pattern", "")
        self.lbl_pattern.config(text=f"  {pattern}" if pattern else "")

        # RSI Diverjansı  YENİ
        rsi_div = r.get("rsi_divergence", "")
        if rsi_div == "bullish":
            self.lbl_divergence.config(text="  📐 RSI Boğa Diverjansı ↗", fg=GREEN)
        elif rsi_div == "bearish":
            self.lbl_divergence.config(text="  📐 RSI Ayı Diverjansı ↘", fg=RED)
        else:
            self.lbl_divergence.config(text="")

        # Metrik kartları
        for w in self.metrics_frm.winfo_children(): w.destroy()
        poc = r.get("poc"); val = r.get("val"); vah = r.get("vah")
        metrics = [
            ("💰 Fiyat",     f"{r['fiyat']:.2f} TL",  FG),
            ("🎯 Puan",      f"{r['puan']:.1f}/10",    score_color(r["puan"])),
            ("📊 RSI (14)",  f"{r['rsi']:.1f}",
             RED if r['rsi']>72 else GREEN if r['rsi']<30 else FG),
            ("⚡ MACD",      f"{r.get('macd',0):.4f}",
             GREEN if r.get('macd',0)>r.get('macd_sig',0) else RED),
            ("🌀 Stoch %K",  f"{r.get('stoch_k',50):.1f}",
             GREEN if r.get('stoch_k',50)<30 else RED if r.get('stoch_k',50)>70 else FG),
            ("📐 ADX",       f"{r.get('adx',0):.1f}",
             GREEN if r.get('adx',0)>25 else YELLOW),
            ("🎲 Olasılık",  f"%{r['prob_up']}",       CYAN),
            ("🧭 Güven",     f"%{r['guven_skoru']}",   BLUE),
            ("⚡ Risk",
             f"{r['risk_skoru']:.1f} — {'DÜŞÜK' if r['risk_skoru']<=2 else 'ORTA' if r['risk_skoru']<=5 else 'YÜKSEK'}",
             GREEN if r['risk_skoru']<=2 else YELLOW if r['risk_skoru']<=5 else RED),
            ("🎯 Hedef",     f"{r['hedef']:.2f} TL",   GREEN),
            ("🛑 Stop-Loss", f"{r['stop']:.2f} TL",    RED),
            ("📈 Beklenen",  f"+%{r['bek_get']:.1f}",  GREEN),
            ("⚖️  Risk/Ödül", f"{r['rr']:.2f}x",
             GREEN if r['rr']>=2 else YELLOW if r['rr']>=1 else RED),
            ("🛒 Destek",    f"{r['destek']:.2f} TL",  FG2),
            ("🔺 Direnç",    f"{r['direnc']:.2f} TL",  ORANGE),
            ("📏 ATR (14)",  f"{r['atr']:.2f} TL",     FG2),
            ("🔲 BB Üst",    f"{r.get('upper_bb',0):.2f} TL", FG3),
            ("🔲 BB Alt",    f"{r.get('lower_bb',0):.2f} TL", FG3),
            ("🔀 BB %B",     f"{r.get('pct_b',0.5):.2f}",     FG2),
            ("🗂️ POC",        f"{poc:.2f} TL" if poc else "—", PURPLE),
            ("⏱ Süre",       r["horizon"],              PURPLE),
            ("✅ TF Uyum",   f"{r.get('aligned_tfs',0)}/{r.get('toplam_tfs',6)}",
             GREEN if r.get('aligned_tfs',0)>=4 else YELLOW),
        ]
        cols = 2
        for idx, (lbl, val_str, clr) in enumerate(metrics):
            card = tk.Frame(self.metrics_frm, bg=BG3, padx=6, pady=3)
            card.grid(row=idx // cols, column=idx % cols,
                      padx=2, pady=2, sticky="ew")
            self.metrics_frm.columnconfigure(idx % cols, weight=1)
            tk.Label(card, text=lbl, bg=BG3, fg=FG2,
                     font=("Segoe UI", 7)).pack(anchor="w")
            tk.Label(card, text=val_str, bg=BG3, fg=clr,
                     font=("Consolas", 10, "bold")).pack(anchor="w")

        # İndikatör özeti
        for w in self.ind_frm.winfo_children(): w.destroy()
        ind_data = [
            ("MACD",     f"{r.get('macd',0):.4f}",
             GREEN if r.get('macd',0)>r.get('macd_sig',0) else RED),
            ("Signal",   f"{r.get('macd_sig',0):.4f}", FG2),
            ("Hist",     f"{r.get('macd_hist',0):.4f}",
             GREEN if r.get('macd_hist',0)>0 else RED),
            ("Stoch%K",  f"{r.get('stoch_k',50):.1f}",
             GREEN if r.get('stoch_k',50)<30 else RED if r.get('stoch_k',50)>70 else FG),
            ("Stoch%D",  f"{r.get('stoch_d',50):.1f}", FG2),
            ("Williams%R", f"{r.get('wpr',-50):.1f}",
             GREEN if r.get('wpr',-50)<-80 else RED if r.get('wpr',-50)>-20 else FG),
            ("CCI",      f"{r.get('cci',0):.0f}",
             GREEN if r.get('cci',0)<-100 else RED if r.get('cci',0)>100 else FG),
            ("ADX",      f"{r.get('adx',0):.1f}",
             GREEN if r.get('adx',0)>25 else YELLOW),
            ("Fib38.2",  f"{r.get('fib',{}).get('38.2','—')}", FG3),
            ("Fib61.8",  f"{r.get('fib',{}).get('61.8','—')}", FG3),
        ]
        for i, (label, value, color) in enumerate(ind_data):
            cf = tk.Frame(self.ind_frm, bg=BG2)
            cf.grid(row=0, column=i, padx=6, pady=2, sticky="ew")
            self.ind_frm.columnconfigure(i, weight=1)
            tk.Label(cf, text=label, bg=BG2, fg=FG3,
                     font=("Segoe UI", 7)).pack(anchor="center")
            tk.Label(cf, text=value, bg=BG2, fg=color,
                     font=("Consolas", 9, "bold")).pack(anchor="center")

        # YENİ: Gelişmiş indikatörler satırı
        for w in self.ind2_frm.winfo_children(): w.destroy()
        st_dir   = r.get("supertrend_dir", 1)
        st_price = r.get("supertrend_price", 0)
        vi_plus  = r.get("vi_plus", 1.0)
        vi_minus = r.get("vi_minus", 1.0)
        mfi_val  = r.get("mfi", 50)
        cloud    = r.get("cloud_signal", "neutral")
        hma_val  = r.get("hma", 0)
        ind2_data = [
            ("MFI",        f"{mfi_val:.1f}",
             GREEN if mfi_val<30 else RED if mfi_val>70 else FG),
            ("Supertrend", f"{'▲ Yukarı' if st_dir==1 else '▼ Aşağı'} {st_price:.2f}",
             GREEN if st_dir==1 else RED),
            ("VI+",        f"{vi_plus:.3f}",
             GREEN if vi_plus>vi_minus else FG2),
            ("VI-",        f"{vi_minus:.3f}",
             RED if vi_minus>vi_plus else FG2),
            ("Ichimoku",   cloud.upper(),
             GREEN if cloud=="bullish" else RED if cloud=="bearish" else YELLOW),
            ("HMA(20)",    f"{hma_val:.2f}",
             GREEN if r.get('fiyat',0)>hma_val else RED),
            ("RSI Div.",   r.get("rsi_divergence","").upper() or "—",
             GREEN if r.get("rsi_divergence")=="bullish"
             else RED if r.get("rsi_divergence")=="bearish" else FG3),
            ("BB Sıkış.",  "EVET" if r.get("true_squeeze") else "HAYIR",
             ORANGE if r.get("true_squeeze") else FG3),
        ]
        for i, (label, value, color) in enumerate(ind2_data):
            cf = tk.Frame(self.ind2_frm, bg=BG3)
            cf.grid(row=0, column=i, padx=6, pady=2, sticky="ew")
            self.ind2_frm.columnconfigure(i, weight=1)
            tk.Label(cf, text=label, bg=BG3, fg=FG3,
                     font=("Segoe UI", 7)).pack(anchor="center")
            tk.Label(cf, text=value, bg=BG3, fg=color,
                     font=("Consolas", 9, "bold")).pack(anchor="center")

        # Grafik
        self.chart_canvas.update_idletasks()
        w = self.chart_canvas.winfo_width() or 560
        draw_price_chart(
            self.chart_canvas,
            r.get("closes_hist",[]), r.get("highs_hist",[]),
            r.get("lows_hist",[]),   r.get("volumes_hist",[]),
            r["hedef"], r["stop"],
            bb_upper=r.get("upper_bb"), bb_lower=r.get("lower_bb"),
            fib_levels=r.get("fib"), width=w, height=240
        )

        # Zaman dilimi tablosu
        for row in self.tf_tree.get_children(): self.tf_tree.delete(row)
        for tf, d in r.get("zaman_dilimleri", {}).items():
            macd_str = f"{d.get('macd',0):+.4f}"
            macd_tag = "buy" if d.get("macd",0)>d.get("macd_sig",0) else "sell"
            self.tf_tree.insert("", tk.END, values=(
                tf, d["durum"], f"{d['puan']:.1f}/10",
                f"{d['degisim']:+.2f}%", f"{d['rsi']:.1f}",
                macd_str, f"{d.get('stoch_k',50):.1f}",
                f"{d.get('adx',0):.1f}",
                f"%{d['guven_skoru']}", d["risk_seviyesi"]
            ), tags=(macd_tag,))
        self.tf_tree.tag_configure("buy",  foreground=GREEN)
        self.tf_tree.tag_configure("sell", foreground=RED)

        # Analiz notu
        note = self._build_note(r)
        self.txt_note.config(state="normal")
        self.txt_note.delete("1.0", tk.END)
        self.txt_note.insert(tk.END, note)
        self.txt_note.config(state="disabled")

    def _build_note(self, r):
        last   = r["fiyat"];  direnc = r["direnc"]; destek = r["destek"]
        rsi_v  = r["rsi"];    stop   = r["stop"];   hedef  = r["hedef"]
        score  = r["puan"];   conf   = r["guven_skoru"]
        macd_h = r.get("macd_hist", 0)
        stoch  = r.get("stoch_k", 50)
        adx    = r.get("adx", 0)
        pat    = r.get("pattern", "")
        fib    = r.get("fib", {})
        aligned = r.get("aligned_tfs", 0)
        total   = r.get("toplam_tfs", 6)
        poc     = r.get("poc")
        cloud   = r.get("cloud_signal", "neutral")
        st_dir  = r.get("supertrend_dir", 1)
        mfi     = r.get("mfi", 50)
        rsi_div = r.get("rsi_divergence", "")

        lines = [f"{'='*48}",
                 f"  {r['hisse']}  |  Puan: {score:.1f}/10  |  Güven: %{conf}",
                 f"{'='*48}"]

        if last >= direnc * 0.99:
            lines.append(f"\n🚀 COŞKU BÖLGESİ — {r['hisse']} direnci ({direnc:.2f} TL) aşmış!")
            lines.append(f"  Stop'u {stop:.2f} TL'ye sıkıştır.")
        elif last <= destek * 1.02:
            lines.append(f"\n🛒 FIRSAT BÖLGESİ — {destek:.2f} TL desteğine yakın!")
        else:
            lines.append(f"\n🎯 HEDEF: {hedef:.2f} TL  |  🛒 FIRSAT: {destek:.2f} TL")

        if fib:
            for level_key in ["38.2", "50.0", "61.8"]:
                fib_v = fib.get(level_key)
                if fib_v and abs(last - fib_v) / last < 0.015:
                    lines.append(f"📐 Fibonacci %{level_key} ({fib_v:.2f} TL) bölgesinde!")
                    break

        lines.append("")
        if rsi_v > 72:    lines.append("⚠️  RSI Aşırı Alım — kâr realizasyonu düşün.")
        elif rsi_v < 30:  lines.append("✅  RSI Aşırı Satım — toparlanma fırsatı olabilir.")
        if rsi_div == "bullish":  lines.append("📐 RSI Boğa Diverjansı — güçlü alım sinyali!")
        elif rsi_div == "bearish": lines.append("📐 RSI Ayı Diverjansı — dikkat!")
        if macd_h > 0:   lines.append("📈 MACD pozitif — momentum yükseliş yönünde.")
        else:             lines.append("📉 MACD negatif — momentum düşüş yönünde.")
        if stoch < 25:    lines.append("🟢 Stochastic aşırı satım bölgesinde.")
        elif stoch > 75:  lines.append("🔴 Stochastic aşırı alım bölgesinde.")
        if adx > 30:      lines.append(f"💪 ADX {adx:.0f} — güçlü trend mevcut.")
        elif adx < 20:    lines.append(f"😴 ADX {adx:.0f} — trend zayıf.")
        if st_dir == 1:   lines.append("🔼 Supertrend: yükseliş tarafında.")
        else:             lines.append("🔽 Supertrend: düşüş tarafında — dikkat!")
        if cloud == "bullish":  lines.append("☁️  Ichimoku: fiyat bulutun üstünde (boğa).")
        elif cloud == "bearish": lines.append("☁️  Ichimoku: fiyat bulutun altında (ayı).")
        if mfi < 20:      lines.append(f"💧 MFI {mfi:.0f} — aşırı satım (hacim onaylı).")
        elif mfi > 80:    lines.append(f"💦 MFI {mfi:.0f} — aşırı alım (hacim onaylı).")
        if pat:           lines.append(f"🕯️  Formasyon: {pat}")

        lines.append(f"\n📊 Zaman Dilimi Uyumu: {aligned}/{total}")
        if aligned >= 5:   lines.append("  → Çok kuvvetli çoklu zaman dilimi uyumu!")
        elif aligned >= 3: lines.append("  → Orta düzey uyum — dikkatli pozisyon.")
        else:              lines.append("  → Zayıf uyum — yüksek risk.")

        if poc: lines.append(f"📦 POC (en yoğun hacim): {poc:.2f} TL")

        lines.append(f"\n{'─'*48}")
        lines.append("📌 YAPILMASI GEREKEN:")
        aksiyon = r["aksiyon"]
        if "GÜÇLÜ AL" in aksiyon:
            lines.append(f"  → Stop: {stop:.2f} TL ile pozisyon aç")
            lines.append(f"  → Hedef: {hedef:.2f} TL'de kısmi kâr al")
            lines.append(f"  → Risk/Ödül: {r['rr']:.2f}x  ✅")
        elif "AL" in aksiyon:
            lines.append(f"  → Dikkatli alım — Stop: {stop:.2f} TL")
            lines.append(f"  → İlk hedef: {hedef:.2f} TL")
        elif "BEKLE" in aksiyon or "İZLE" in aksiyon:
            lines.append(f"  → {direnc:.2f} TL üzeri kapanış bekle")
        elif "SAT" in aksiyon or "ÇIKIŞ" in aksiyon:
            lines.append(f"  → Pozisyonları kademeli kapat")
            lines.append(f"  → {destek:.2f} TL kırılırsa hızla çık")
        elif "AŞIRI" in aksiyon:
            lines.append(f"  → RSI ({rsi_v:.1f}) tehlikeli seviyede")
            lines.append(f"  → Stop'u {stop:.2f} TL'ye sıkıştır")
        else:
            lines.append("  → Yönü netleşene kadar bekle")

        lines.append(f"{'─'*48}")
        lines.append(f"Güncellendi: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════
    # İZLEME LİSTESİ
    # ══════════════════════════════════════════════════════════════════════
    def _wl_add(self):
        sym = self.entry_wl.get().strip().upper()
        if not sym or sym in self.watchlist: return
        self.watchlist.append(sym)
        self.entry_wl.delete(0, tk.END)
        threading.Thread(target=self._wl_fetch_one, args=(sym,), daemon=True).start()

    def _wl_fetch_one(self, sym):
        closes, volumes, highs, lows, opens = self.fetcher.fetch(sym)
        res = analyze(sym, closes, volumes, highs, lows, opens, self.benchmark)
        if res: self.after(0, lambda r=res: self._wl_insert(r))

    def _wl_insert(self, r):
        tag = self._tag(r["aksiyon"])
        iid = r["hisse"]
        if self.wl_tree.exists(iid): self.wl_tree.delete(iid)
        st = "▲ Yukarı" if r.get("supertrend_dir", 1) == 1 else "▼ Aşağı"
        self.wl_tree.insert("", tk.END, iid=iid, values=(
            r["hisse"], f"{r['fiyat']:.2f}", f"{r['rsi']:.1f}",
            f"{r['puan']:.1f}", r["aksiyon"],
            f"{r['hedef']:.2f}", f"{r['stop']:.2f}",
            f"{r['bek_get']:+.1f}%",
            f"{r.get('aligned_tfs',0)}/{r.get('toplam_tfs',6)}",
            st
        ), tags=(tag,))

    def _wl_remove(self):
        sel = self.wl_tree.selection()
        if not sel: return
        for s in sel:
            sym = self.wl_tree.item(s, "values")[0]
            if sym in self.watchlist: self.watchlist.remove(sym)
            self.wl_tree.delete(s)

    def _wl_refresh(self):
        syms = list(self.watchlist)
        for row in self.wl_tree.get_children(): self.wl_tree.delete(row)
        for sym in syms:
            threading.Thread(target=self._wl_fetch_one, args=(sym,),
                             daemon=True).start()

    def _wl_double(self, event):
        sel = self.wl_tree.selection()
        if not sel: return
        sym    = self.wl_tree.item(sel[0], "values")[0]
        cached = next((r for r in self.rapor if r["hisse"] == sym), None)
        if cached:
            self.nb.select(1); self._show_detail(cached)
        else:
            self.nb.select(1)
            self.entry_sym.delete(0, tk.END)
            self.entry_sym.insert(0, sym)
            self._analyze_single()

    # ══════════════════════════════════════════════════════════════════════
    # PİYASA ÖZETİ
    # ══════════════════════════════════════════════════════════════════════
    def _update_market_summary(self):
        if not self.rapor: return
        total    = len(self.rapor)
        buy_cnt  = sum(1 for r in self.rapor if action_bucket(r.get("aksiyon",""))=="buy")
        sell_cnt = sum(1 for r in self.rapor if action_bucket(r.get("aksiyon",""))=="sell")
        wait_cnt = sum(1 for r in self.rapor
                       if action_bucket(r.get("aksiyon","")) in ("wait","overbought","neutral"))
        avg_puan = sum(r["puan"] for r in self.rapor) / total
        avg_rsi  = sum(r["rsi"]  for r in self.rapor) / total
        top = max(self.rapor, key=lambda x: x["puan"])
        bot = min(self.rapor, key=lambda x: x["puan"])

        self.mkt_cards["total"].config(text=str(total))
        self.mkt_cards["buy_cnt"].config(text=str(buy_cnt))
        self.mkt_cards["sell_cnt"].config(text=str(sell_cnt))
        self.mkt_cards["wait_cnt"].config(text=str(wait_cnt))
        self.mkt_cards["avg_puan"].config(text=f"{avg_puan:.1f}")
        self.mkt_cards["avg_rsi"].config(text=f"{avg_rsi:.1f}")
        self.mkt_cards["top_hisse"].config(text=f"{top['hisse']} ({top['puan']:.1f})")
        self.mkt_cards["bottom_h"].config(text=f"{bot['hisse']} ({bot['puan']:.1f})")

        for row in self.top10_tree.get_children(): self.top10_tree.delete(row)
        top10 = sorted(self.rapor, key=lambda x: x["puan"], reverse=True)[:10]
        for i, r in enumerate(top10, 1):
            tag = self._tag(r["aksiyon"])
            st  = "▲" if r.get("supertrend_dir",1)==1 else "▼"
            self.top10_tree.insert("", tk.END, values=(
                i, r["hisse"], f"{r['puan']:.1f}",
                r["aksiyon"], f"{r['bek_get']:+.1f}%",
                f"{r['rr']:.2f}x", st, r.get("pattern","")
            ), tags=(tag,))

        self.lbl_mkt_status.config(
            text=f"Güncellendi: {datetime.now().strftime('%H:%M:%S')}  |  "
                 f"AL: {buy_cnt}  SAT: {sell_cnt}  İZLE: {wait_cnt}", fg=FG2)

    def _top10_double(self, event):
        sel = self.top10_tree.selection()
        if not sel: return
        sym    = self.top10_tree.item(sel[0], "values")[1]
        cached = next((r for r in self.rapor if r["hisse"] == sym), None)
        if cached:
            self.nb.select(1); self._show_detail(cached)

    # ══════════════════════════════════════════════════════════════════════
    # CSV EXPORT
    # ══════════════════════════════════════════════════════════════════════
    def _export_csv(self):
        if not self.rapor:
            messagebox.showwarning("Uyarı", "Önce tarama yapın."); return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Dosyası","*.csv"),("Tümü","*.*")],
            initialfile=f"BIST_Tarama_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        )
        if not path: return
        fields = ["hisse","fiyat","rsi","puan","aksiyon","hedef","stop",
                  "bek_get","rr","guven_skoru","risk_skoru","adx",
                  "stoch_k","macd","pattern","horizon","destek","direnc","atr",
                  "mfi","supertrend_dir","cloud_signal","rsi_divergence"]  # YENİ alanlar
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader(); w.writerows(self.rapor)
            messagebox.showinfo("Başarılı", f"CSV kaydedildi:\n{path}")
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # YENİ YARDIMCILAR
    # ══════════════════════════════════════════════════════════════════════
    def _clear_cache(self):
        self.fetcher.cache_clear()
        messagebox.showinfo("Önbellek", "Önbellek temizlendi.")
        self._update_cache_label()

    def _update_cache_label(self):
        stats = self.fetcher.cache_stats()
        self.lbl_cache.config(
            text=f"Önbellek: {stats['fresh']} taze / {stats['total']} toplam")
        self.after(30000, self._update_cache_label)

    def _tick_clock(self):
        self.lbl_time.config(text=datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))
        self.after(1000, self._tick_clock)


# ══════════════════════════════════════════════════════════════════════════════
# BAŞLAT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = BISTApp()
    app.mainloop()
