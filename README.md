# Hybrid Form Automation

> Sistem automasi pengisian form berbasis arsitektur **Strict Deterministic Routing**. Sistem ini secara cerdas mendeteksi jenis pelindung pada suatu halaman (seperti reCAPTCHA, Turnstile, atau Math Puzzle), kemudian mengarahkan eksekusinya ke engine browser (Playwright atau Selenium) yang paling optimal secara otomatis. Dibangun untuk efisiensi, stealth, dan ketahanan terhadap mekanisme validasi bot modern.

---

## Arsitektur Sistem — Strict Deterministic Routing

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR (main.py)                          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │    PHASE 1: Scanner       │
                     │    HTTP GET / Playwright  │
                     │    Deteksi Field & Bot    │
                     └─────────────┬─────────────┘
                                   │
                             captcha_type?
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
  NONE / math_puzzle      cloudflare_turnstile         Tidak Dikenal
  google_recaptcha                 │                         │
         │                         │                         │
┌────────▼────────┐        ┌───────▼───────┐         ┌───────▼───────┐
│     ROUTE A     │        │    ROUTE B    │         │    ROUTE C    │
│   Playwright    │        │   Selenium    │         │    ABORT      │
│  headless=True  │        │ headless=False│         │ (Log Error)   │
└────────┬────────┘        └───────┬───────┘         └───────────────┘
         │                         │
         ▼                         ▼
  FormExecutor           TurnstileFormExecutor
 (executor.py)          (selenium_executor.py)
```

---

## Deskripsi Fase Kerja

### Phase 1 — Form Scanner (`scanner.py`)

Pemindai ini berjalan 100% **headless (siluman)**. Awalnya, ia melakukan `GET request` ringan untuk mem-parse HTML mentah dan mengekstrak _FormMetadata_ (struktur field, honeypot, jenis captcha). Jika gagal (karena halaman berupa SPA/dirender JavaScript), scanner otomatis melakukan _fallback_ menggunakan Playwright murni di latar belakang untuk merender DOM, lalu mengekstrak informasinya. Output dari fase ini diserahkan ke _Orchestrator/Router_.

### Phase 2 — Strict Routing & Execution

Berdasarkan parameter captcha dari `FormMetadata`, `main.py` mengarahkan eksekusi ke engine yang tepat:

1. **Playwright Executor (`executor.py`)**  
   **Target:** Halaman tanpa Captcha, reCAPTCHA v2 (Audio Challenge), dan Math Puzzle.  
   **Mode:** `headless=True` (berjalan di background tanpa GUI).  
   Menggunakan `playwright` murni dengan stealth init script untuk menghapus fingerprint `navigator.webdriver`. Pengisian menggunakan simulasi _typing_ manusia dan solver terintegrasi (contoh: `pydub` untuk audio reCAPTCHA).

2. **Selenium Executor (`selenium_executor.py` + `turnstile_solver/`)**  
   **Target:** Cloudflare Turnstile.  
   **Mode:** `headless=False` (browser GUI terbuka penuh).  
   Karena Turnstile sangat agresif dalam mendeteksi browser headless, executor ini memutar haluan menggunakan Selenium + `undetected-chromedriver` dalam mode GUI penuh untuk mensimulasikan lingkungan pengguna nyata. Modul `turnstile_solver` menangani deteksi koordinat dan klik secara _humanized_.

### Phase 3 — Validasi & Cleanup

Setelah menekan tombol _submit_, sistem tidak langsung menutup sesi. Executor memverifikasi respons di halaman (apakah ada teks/toast indikator sukses atau _error connection_). Setelah sukses (atau gagal pada percobaan maksimal), instance browser dihancurkan untuk membebaskan memori.

---

## Struktur Direktori

```text
project-root/
├── main.py              # Orkestrator utama — Strict Deterministic Routing Engine
├── scanner.py           # Phase 1: Pre-flight HTTP & Playwright fallback scanner
├── executor.py          # Phase 2: Playwright stealth executor (None/Native/reCAPTCHA)
├── selenium_executor.py # Phase 2: Selenium UC-driver executor (Cloudflare Turnstile)
├── solver.py            # Modul solver captcha dasar (Math puzzle & Audio reCAPTCHA)
├── humanizer.py         # Primitif humanisasi keyboard dan mouse (khusus Playwright)
├── turnstile_solver/    # Paket khusus Selenium Turnstile solver (detector, clicker, matcher)
├── config.py            # URL, selector, dan parameter target
├── README.md            # Dokumentasi ini
├── AGENT.md             # Panduan pengembangan dan kontrak arsitektur
└── requirements.txt     # Dependensi Python
```

---

## Instalasi

### Prasyarat

- Python 3.11+
- `pip`
- Google Chrome terinstal di sistem (diperlukan oleh `undetected-chromedriver`)

### Langkah Setup

```bash
# 1. Clone atau salin proyek ke direktori kerja
cd project-root

# 2. Buat dan aktivasi virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

# 3. Instal semua dependensi Python
pip install -r requirements.txt

# 4. Unduh binary browser bawaan Playwright
playwright install chromium
```

---

## Konfigurasi

Semua konfigurasi target dan _bank data_ pengisian form dipusatkan di `config.py`. Anda dapat menyesuaikan URL, field tambahan opsional, dan bank data identitas.

```python
# config.py
from dataclasses import dataclass, field

@dataclass
class Config:
    url: str = "https://target-domain.example/contact"

    # Selector non-dinamis
    robot_checkbox_selector: str = "[type='checkbox']"
    submit_selector: str         = "button[type='submit']"

    # Data identitas dinamis yang akan diinjeksi ke dalam form
    form_data_bank: dict = field(default_factory=lambda: {
        "nama":    "Vora Automation",
        "email":   "vora@test-domain.io",
        "pesan":   "Pesan otomatis untuk pengujian bot protection.",
        "company": "Vora Industries"
    })

QNN_CONFIG = Config()
```

---

## Penggunaan

Jalankan orkestrator secara langsung:

```bash
python main.py
```

Sistem akan otomatis menentukan apakah harus menggunakan **Playwright (Background)** atau **Selenium (GUI)**. Anda cukup duduk manis dan melihat output log-nya.

### Output Log (Contoh reCAPTCHA via Playwright)

```text
[16:28:01] INFO     | [Phase 1] Scan selesai. Fields: 3, Captcha: True (google_recaptcha)
[16:28:01] INFO     | [ROUTER] Captcha 'google_recaptcha' terdeteksi → Menggunakan Playwright Executor (headless=True)
[16:28:06] INFO     | [Phase 2] Mengisi field form dengan human_type_burst...
[16:28:18] INFO     | Memulai pemecahan Google reCAPTCHA menggunakan Audio Challenge.
[16:28:25] INFO     |   -> Hasil Transkripsi: 'are any one particular'
[16:28:27] INFO     |   -> [OK] reCAPTCHA berhasil dipecahkan.
[16:28:30] INFO     |   -> [OK] Tidak ditemukan pesan error. Asumsi submit berhasil.
[16:28:32] INFO     | ─── Siklus automasi selesai dengan status: BERHASIL ───
```

### Output Log (Contoh Turnstile via Selenium)

```text
[10:15:01] INFO     | [Phase 1] Scan selesai. Fields: 4, Captcha: True (cloudflare_turnstile)
[10:15:01] INFO     | [ROUTER] Captcha 'cloudflare_turnstile' terdeteksi → Menggunakan Selenium Executor (GUI / headless=False)
[10:15:05] INFO     | [Phase 2 / Selenium] Mengisi field form (humanized)...
[10:15:15] INFO     | [Phase 2 / Selenium] Menjalankan Turnstile solver...
[10:15:20] INFO     |   -> [OK] Token Turnstile diperoleh (panjang=482).
[10:15:25] INFO     |   -> [OK] Indikator sukses ditemukan pada halaman.
[10:15:26] INFO     | ─── Siklus automasi selesai dengan status: BERHASIL ───
```

---

## Lisensi

Proyek ini dikembangkan untuk tujuan **riset, pengujian sistem sekuritas, dan edukasi arsitektur otomatisasi hybrid**. Penggunaan terhadap sistem pihak ketiga tanpa izin eksplisit dari pemilik sistem merupakan tanggung jawab penuh pengguna akhir.
