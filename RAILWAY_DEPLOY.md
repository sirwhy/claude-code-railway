# Deploy ke Railway

Panduan langkah demi langkah untuk deploy bot ini ke Railway dengan PostgreSQL.

## Prasyarat

- Akun [Railway](https://railway.app)
- Telegram Bot Token dari [@BotFather](https://t.me/BotFather)
- Anthropic API Key dari [console.anthropic.com](https://console.anthropic.com)

---

## Langkah 1 — Buat Project Railway

1. Login ke [railway.app](https://railway.app) → **New Project**
2. Pilih **Deploy from GitHub repo** → hubungkan repo ini
   - Atau pilih **Empty Project** lalu push repo lewat Railway CLI

---

## Langkah 2 — Tambahkan PostgreSQL

1. Di dalam project Railway, klik **+ New** → **Database** → **Add PostgreSQL**
2. Railway otomatis inject variabel `DATABASE_URL` ke semua service dalam project ini
3. Tidak perlu konfigurasi manual — database akan dipakai otomatis

---

## Langkah 3 — Set Environment Variables

Di Service → **Variables**, tambahkan variabel berikut:

| Variable | Nilai | Keterangan |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `123456:ABC...` | Token dari @BotFather |
| `TELEGRAM_BOT_USERNAME` | `nama_bot_kamu` | Username bot tanpa @ |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | API key untuk proxy/9router kamu |
| `ANTHROPIC_BASE_URL` | `https://cli-proxy-api-production-d321.up.railway.app/v1` | Base URL proxy 9router |
| `ALLOWED_USERS` | `123456789` | Telegram user ID kamu (pisah koma jika banyak) |
| `APPROVED_DIRECTORY` | `/workspace` | Direktori kerja bot (sudah dibuat di container) |
| `USE_SDK` | `true` | Gunakan Anthropic Python SDK |
| `ENVIRONMENT` | `production` | Mode produksi |
| `DEBUG` | `false` | Nonaktifkan debug mode |
| `DEVELOPMENT_MODE` | `false` | Nonaktifkan dev mode |
| `LOG_LEVEL` | `INFO` | Level logging |

> **DATABASE_URL** otomatis ter-inject dari plugin PostgreSQL — tidak perlu diisi manual.

Lihat `.env.railway` untuk daftar lengkap variabel opsional.

---

## Langkah 4 — Deploy

Railway akan otomatis build dari `Dockerfile` dan deploy saat ada push ke branch utama.

Untuk deploy manual:
```bash
railway up
```

---

## Langkah 5 — Cek Logs

Di Railway → Service → **Logs** untuk memastikan bot berjalan:

```
{"event": "Starting Claude Code Telegram Bot", ...}
{"event": "Database initialization complete", "backend": "postgresql", ...}
{"event": "Bot started successfully", ...}
```

---

## Cara Mendapatkan Telegram User ID

Kirim pesan ke bot [@userinfobot](https://t.me/userinfobot) untuk mendapatkan user ID kamu.

---

## Fitur Opsional

### Voice Transcription
Tambahkan ke Variables:
```
ENABLE_VOICE_MESSAGES=true
VOICE_PROVIDER=mistral
MISTRAL_API_KEY=your_key
```

### API Webhook Server (FastAPI)
```
ENABLE_API_SERVER=true
API_SERVER_PORT=8080
```

---

## Catatan

- Bot menggunakan **polling** (bukan webhook) — tidak butuh domain/SSL untuk operasi dasar
- Data tersimpan di PostgreSQL Railway — persisten meski container restart
- `/workspace` di container adalah direktori default untuk project files bot
