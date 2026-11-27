# Generate Video

Project terpisah untuk membuat video AI multi-scene menggunakan Agnes AI melalui GitHub Actions. Workflow ini tidak mengubah atau bergantung pada repository AI Shorts existing.

## Cara menjalankan

1. Buka **Settings → Secrets and variables → Actions**.
2. Tambahkan repository secret bernama `AGNES_API_KEY` dengan API key dari [Agnes AI](https://platform.agnes-ai.com).
3. Buka tab **Actions**.
4. Pilih **Generate AI Video** → **Run workflow**.
5. Isi ide cerita, gaya visual, jumlah scene, durasi, dan opsi narasi.
6. Setelah job selesai, unduh file MP4 dari bagian **Artifacts** pada halaman run.

## Yang dijalankan workflow

- Mengunduh engine open-source [uglylee/free-video-generator](https://github.com/uglylee/free-video-generator) saat job berjalan.
- Menjalankan Python + FFmpeg di GitHub-hosted runner (tanpa GPU lokal).
- Memanggil Agnes AI untuk membuat video multi-scene.
- Mengunduh hasil akhir sebagai `output/generated-video.mp4`.
- Mengunggah MP4 sebagai artifact dengan retensi 3 hari.

## Penanganan rate limit Agnes

- Workflow menerapkan batas konservatif 5 request/menit (efektif sekitar 4 request/menit) dan menonaktifkan burst request.
- Jika Agnes mengembalikan HTTP 429, engine mencoba ulang hingga 5 kali dengan jeda 30, 60, 90, dan 120 detik.
- Pengaturan ini membantu menghadapi rate limit sementara. Jika kuota/kredit akun habis atau batas harian tercapai, retry tidak dapat mengatasinya; periksa kuota dan status akun Agnes.

## Catatan penting

- Agnes API key wajib tersedia sebagai GitHub Secret. Jangan menaruh API key di prompt, file, atau commit.
- Workflow menggunakan format portrait 768×1152 (9:16), mode scene chaining `keyframes`, subtitle aktif, dan voice TTS `id-ID-ArdiNeural`.
- Repository upstream saat ini mendokumentasikan empat voice bawaan berbahasa Mandarin. Workflow mencoba voice Edge TTS Indonesia `id-ID-ArdiNeural`; keberhasilannya perlu diverifikasi pada run pertama. Jika provider menolak voice tersebut, ubah input/env `AUDIO_VOICE` pada workflow ke voice yang didukung.
- Gratis atau tidaknya penggunaan Agnes AI bergantung pada kebijakan, kuota, dan ketersediaan layanan Agnes saat workflow dijalankan. GitHub Actions juga memiliki kuota menit dan penyimpanan artifact sesuai paket akun.
- GitHub-hosted runner bersifat sementara. Job yang berhenti tidak menyimpan state pipeline untuk dilanjutkan di job berikutnya.
- Kode engine upstream diambil dari branch `main` pada saat workflow berjalan; perubahan upstream dapat memengaruhi kompatibilitas.
- Engine upstream berlisensi MIT. Lihat repository upstream untuk lisensi, dokumentasi, dan perubahan terbaru.

## Struktur

```
.github/workflows/generate-video.yml  # Manual workflow dispatch
scripts/run_generator.py             # Submit task, polling, download MP4
scripts/patch_engine.py              # Conservative Agnes retry/rate-limit settings
requirements-generator.txt           # Dependensi runner
```
