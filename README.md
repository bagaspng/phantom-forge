# XoS Hybrid Form Automation

> Sistem automasi pengisian form berbasis arsitektur **Hybrid Pre-flight** yang memisahkan beban kerja DOM scanning ringan (Phase 1) dari eksekusi interaksi dinamis berbobot (Phase 2–4). Dibangun untuk efisiensi maksimal, stealth fingerprint modern, dan ketahanan terhadap mekanisme validasi JavaScript sisi klien.

---

## Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (main.py)                           │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
         ┌─────────────▼─────────────┐
         │   PHASE 1: Pre-flight      │  requests + BeautifulSoup
         │   FormScanner              │  HTTP GET → BS4 parse
         │   Output: FormMetadata     │  Waktu target: <200ms
         └─────────────┬─────────────┘
                       │ Handoff: FormMetadata
         ┌─────────────▼─────────────┐
         │   PHASE 2: Init Browser    │  Playwright Chromium
         │   FormExecutor             │  Stealth context
         │   Navigasi & DOM ready     │  add_init_script injeksi
         └─────────────┬─────────────┘
                       │
         ┌─────────────▼─────────────┐
         │   PHASE 3: Trigger & Solve │  page.fill() → native JS events
         │   Fill → Captcha → Submit  │  MutationObserver pada [disabled]
         │   Turnstile handler        │  solve_puzzle() integration
         └─────────────┬─────────────┘
                       │
         ┌─────────────▼─────────────┐
         │   PHASE 4: Cleanup         │  browser.close()
         │   Memori & proxy flush     │  Isolasi sesi per iterasi
         └───────────────────────────┘
```

---

## Deskripsi Fase

### Phase 1 — Pre-flight Scanner (`scanner.py`)

Melakukan `GET request` ringan ke URL target tanpa memuat JavaScript engine. `BeautifulSoup` mem-parse HTML mentah dan menghasilkan `FormMetadata`: peta field `{name_attr → css_selector}`, daftar honeypot yang diabaikan, selector tombol submit, serta flag dan signature captcha. Fase ini tidak membuka browser sama sekali — overhead setara satu HTTP request biasa.

### Phase 2 — Browser Initialization (`executor.py`)

Menerima `FormMetadata` dari Phase 1 dan menginisialisasi konteks Playwright Chromium. Injeksi stealth script dilakukan via `context.add_init_script()` sebelum dokumen pertama dimuat, menghapus fingerprint `navigator.webdriver` dan properti otomatisasi lainnya dari perspektif JavaScript sisi klien.

### Phase 3 — Trigger & Solve (`executor.py → execute()`)

Loop pengisian field menggunakan `page.fill()` yang secara internal memicu chain event `focus → keydown → input → change → blur` — identik dengan input keyboard manusia. Jika captcha gate terdeteksi:

- **Checkbox robot**: `page.click()` pada checkbox → `page.wait_for_selector()` menunggu elemen pertanyaan muncul → `solve_puzzle()` menghitung jawaban → injeksi ke field captcha.
- **Cloudflare Turnstile**: klik iframe `.cf-turnstile` disertai simulasi pergerakan mouse acak menggunakan `page.mouse.move()` untuk melewati deteksi behavioral.
- Validasi state tombol submit menggunakan `page.locator(submit_selector).wait_for(state="enabled")` yang bereaksi terhadap mutasi DOM secara reaktif — tanpa `time.sleep()`.

### Phase 4 — Cleanup

`browser.close()` membuang seluruh konteks Chromium, cache session, dan cookie sesi. Pada konfigurasi multi-iterasi dengan rotasi proxy, pola ini memastikan setiap siklus mendapatkan identitas jaringan yang bersih tanpa kontaminasi sesi sebelumnya.

---

## Struktur Direktori

```
project-root/
├── main.py              # Orkestrator utama — titik masuk eksekusi
├── scanner.py           # Phase 1: Pre-flight HTTP scanner
├── executor.py          # Phase 2–4: Playwright stealth executor
├── solver.py            # Modul pemecah teka-teki / kalkulasi captcha
├── config.py            #  URL, selector, dan parameter target
├── README.md            # Dokumentasi ini
├── AGENT.md             # Panduan pengembangan dan kontrak arsitektur
└── requirements.txt     # Dependensi Python
```

---

## Instalasi

### Prasyarat

- Python 3.11+
- pip

### Langkah Setup

```bash
# 1. Clone atau salin proyek ke direktori kerja
cd project-root

# 2. Buat dan aktivasi virtual environment
python -m venv venv
# Untuk Windows:
venv\Scripts\activate
# Untuk macOS/Linux:
# source venv/bin/activate

# 3. Instal dependensi Python
pip install -r requirements.txt

# 4. Unduh binary Chromium yang dioptimasi Playwright
playwright install chromium
```

### `requirements.txt`

```
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
playwright>=1.44.0
```

---

## Konfigurasi

Edit `config.py` untuk menyesuaikan target:

```python
# config.py
from dataclasses import dataclass, field

@dataclass
class Config:
    url: str = "https://target-domain.example/kontak-kami"
    form_selectors: dict = field(default_factory=lambda: {
        "nama":   "[name='nama']",
        "judul":  "[name='judul']",
        "email":  "[name='email']",
        "pesan":  "[name='pesan']",
    })
    robot_checkbox_selector: str = "[type='checkbox']"
    submit_selector: str         = "button[type='submit']"

QNN_CONFIG = Config()
```

---

## Penggunaan

```bash
python main.py
```

Atau secara programatik dari modul lain:

```python
from main import run_hybrid_automation

run_hybrid_automation(
    target_url="https://target-domain.example/kontak-kami",
    form_data={
        "nama":   "Vora Arsitek",
        "judul":  "Pengujian Sistem",
        "email":  "vora@test-domain.io",
        "pesan":  "Pesan uji coba automasi hybrid.",
    },
    proxy_url="http://192.168.1.1:8080",  # None jika tidak menggunakan proxy
)
```

---

## Variabel Output & Logging

Setiap fase menghasilkan log terstruktur ke `stdout`:

```
[10:23:41] INFO     | [Phase 1] Memulai pre-flight HTTP scan ke: https://...
[10:23:41] INFO     |   [MAP] 'nama' → '[name="nama"]'
[10:23:41] INFO     | [Phase 1] Scan selesai. Fields: 4, Captcha: Ya, Honeypots: 1
[10:23:42] INFO     | [Phase 2] Inisialisasi Playwright executor...
[10:23:43] INFO     | [Phase 3] Mengisi field form...
[10:23:44] INFO     |   -> Payload captcha: '12 + 7 = ?'
[10:23:44] INFO     |   -> Kalkulasi solver: 19
[10:23:45] INFO     | [Phase 4] Browser instance ditutup. Memori dibebaskan.
[10:23:45] INFO     | ─── Siklus automasi selesai dengan status: BERHASIL ───
```

Screenshot error disimpan otomatis ke `error_playwright.png` jika terjadi kegagalan pada Phase 2–3.

---

## Keterbatasan yang Diketahui

| Kondisi                                            | Perilaku Saat Ini                        | Status                               |
| -------------------------------------------------- | ---------------------------------------- | ------------------------------------ |
| Turnstile dengan behavioral challenge kompleks     | Simulasi mouse dasar mungkin tidak cukup | Dalam pengembangan                   |
| Form yang sepenuhnya dirender via JavaScript (SPA) | Phase 1 tidak dapat memetakan field      | Gunakan Phase 2 full-render fallback |
| Proxy rate-limiting                                | Tidak ada retry logic bawaan             | Direncanakan pada v0.3               |
| CAPTCHA gambar / reCAPTCHA v2 visual               | Belum didukung solver                    | Memerlukan integrasi API eksternal   |

---

## Lisensi

Proyek ini dikembangkan untuk tujuan **riset, pengujian sistem, dan edukasi arsitektur otomatisasi**. Penggunaan terhadap sistem pihak ketiga tanpa izin eksplisit dari pemilik sistem merupakan tanggung jawab penuh pengguna.
