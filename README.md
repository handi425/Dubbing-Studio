# Dubbing Studio

Aplikasi lokal Windows untuk menerjemahkan video Inggris dan membuat sulih suara Indonesia dengan suara Microsoft Ardi atau Gadis.

## Menjalankan

Klik dua kali **MULAI DUBBING.bat** pada folder kursus. Aplikasi terbuka di http://127.0.0.1:8765. Biarkan jendela server berjalan selama pemrosesan. Instalasi pertama memerlukan internet. Python 3.10–3.13 dan FFmpeg/FFprobe harus ada di PATH; keduanya sudah ditemukan pada komputer saat pembuatan aplikasi.

1. Pilih video dari pustaka kursus atau unggah video sendiri (maksimum 8 GB).
2. Pilih suara **Ardi** (pria) atau **Gadis** (wanita), kecepatan, dan volume suara asli.
3. Klik **Terjemahkan video**. Subtitle `.vtt`/`.srt` yang cocok dipakai otomatis, termasuk penamaan `CHP 1 ...` pada kursus ini. Anda bisa memilih subtitle Inggris sendiri.
4. Tanpa subtitle, Whisper mentranskripsi bahasa Inggris di CPU lokal. Model diunduh pada pemakaian pertama; proses dapat lambat pada video panjang.
5. Periksa dan edit terjemahan, lalu klik **Buat video dubbing**.
6. Putar atau unduh MP4, subtitle Indonesia/Inggris, dan transkrip bilingual.

Hasil berada di `DubbingStudio/data/<id-proyek>/hasil.mp4`. Video asli tidak diubah. Riwayat proyek tetap tersedia setelah aplikasi ditutup. Proses berjalan satu per satu; tombol batalkan menunggu operasi jaringan/model yang sedang berjalan selesai. Setelah gangguan, klik **Lanjutkan / coba lagi**. Cache terjemahan dan audio dipakai kembali. Pada proses transkripsi yang terputus, transkripsi dimulai lagi.

## Layanan dan koneksi

- Suara default memakai layanan Microsoft Edge melalui [edge-tts](https://github.com/rany2/edge-tts), pustaka pihak ketiga, tanpa API key. Ini bukan SDK Azure resmi dan ketersediaannya dapat berubah.
- Terjemahan default memakai model Inggris–Indonesia [Argos](https://github.com/argosopentech/argospm-index) melalui CTranslate2 di komputer. Model sekitar 65 MB diunduh sekali, kemudian dapat dipakai offline. Model sudah disiapkan pada komputer ini.
- Google web dan Microsoft Translator tersedia sebagai pilihan penerjemah online. Google web bukan Cloud Translation API resmi; layanan ini menolak permintaan saat pengujian, sehingga bukan pilihan utama.
- Video tetap di komputer. Dengan penerjemah lokal, teks Inggris tetap lokal. **Untuk suara Microsoft, teks Indonesia dikirim ke Microsoft.** Bila memilih penerjemah online, teks Inggris juga dikirim ke layanan itu. Font antarmuka dimuat dari Google Fonts dengan fallback font sistem.
- Transkripsi menggunakan [faster-whisper](https://github.com/SYSTRAN/faster-whisper) secara lokal setelah model tersedia.
- Tidak ada jaminan ketepatan terjemahan istilah teknis. Editor membantu memeriksa hasil sebelum dibuat suara.

## Menggunakan Microsoft Azure resmi (opsional)

Atur environment berikut melalui Windows Environment Variables atau PowerShell sebelum menjalankan aplikasi. Jangan masukkan key ke kode atau membagikannya.

```powershell
$env:AZURE_SPEECH_KEY = 'key-Anda'
$env:AZURE_SPEECH_REGION = 'southeastasia'
$env:AZURE_TRANSLATOR_KEY = 'key-Anda'
$env:AZURE_TRANSLATOR_REGION = 'southeastasia'
.\.venv\Scripts\python.exe app.py
```

Gunakan region sesuai resource Azure Anda. Pilih **Azure Speech** dan/atau **Microsoft Translator** di Pengaturan layanan. Penggunaan mengikuti tarif akun Azure. Aplikasi tidak membuat resource atau langganan Azure.

Referensi: [Microsoft Speech REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech), [Microsoft Translator Translate](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/v3/translate), [daftar suara Microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support).

## Suara Wikidepia secara lokal

Integrasi model [Wikidepia/indonesian-tts](https://github.com/Wikidepia/indonesian-tts) v1.2 tersedia di **Pengaturan layanan → Mesin suara → Wikidepia Ardi/Gadis · offline**. Suara Ardi/Gadis pada model ini dilatih dari contoh Azure; ini model lokal, bukan layanan Microsoft Azure langsung. Model asal membatasi pemakaian untuk **nonkomersial**.

Jalankan `PASANG SUARA LOKAL.bat` untuk menyiapkan Python 3.11 terpisah, PyTorch CPU, Coqui TTS, g2p-id resmi Wikidepia, dan model sekitar 330 MB. Dependensi membutuhkan tambahan ruang disk beberapa GB. Setelah pemasangan, penerjemah lokal + suara Wikidepia dapat digunakan tanpa koneksi internet. CPU dapat lebih lambat daripada layanan Microsoft. Sumber upstream tersimpan di `vendor/indonesian-tts`; aplikasi drat tidak digunakan oleh integrasi ini.

Kecepatan berbicara diterapkan pada VITS `length_scale`. Model dimuat sekali untuk setiap proses dubbing, lalu hasil suara tiap bagian disimpan di cache. Angka dan persen dinormalisasi ke pengucapan Indonesia sebelum dikonversi ke fonem.

## Sinkronisasi dan hasil

Kalimat subtitle yang terpotong digabung selama waktunya berdekatan. Setiap ucapan Indonesia dimulai mengikuti timestamp sumber; jika terlalu panjang, suara dipercepat agar tidak menimpa kalimat berikutnya. Bagian dengan percepatan besar ditandai agar terjemahan bisa diringkas. Ini sinkronisasi narasi, bukan sinkronisasi gerakan bibir atau kloning suara. Intro, jeda, dan durasi video dipertahankan.

MP4 menyertakan audio Indonesia sebagai track default, audio asli sebagai track kedua jika tersedia, dan subtitle Indonesia yang bisa dinyalakan/dimatikan. Pemutar aplikasi menampilkan subtitle melalui track VTT. Browser umumnya hanya memutar track audio pertama; gunakan VLC untuk memilih track Inggris. Mode volume asli mencampur seluruh audio sumber, bukan memisahkan musik dari suara pembicara. Video H.264 disalin tanpa encode ulang; codec lain dikonversi ke H.264.

## Pengembangan dan pemeriksaan

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --no-browser
```

`DUBBING_LIBRARY` mengatur folder pustaka, `DUBBING_PORT` mengubah port. Server hanya mendengarkan 127.0.0.1. Jangan mengeksposnya ke internet. Jika port 8765 sudah dipakai aplikasi ini, launcher membuka aplikasi yang sedang berjalan.

## Pemecahan masalah

- **Microsoft/terjemahan gagal:** periksa internet, coba kembali; pertimbangkan Azure jika layanan web tidak tersedia.
- **FFmpeg tidak ditemukan:** instal FFmpeg dan tambahkan folder `bin` ke PATH, lalu buka ulang launcher.
- **Model gagal diunduh:** periksa akses ke Hugging Face, atau gunakan subtitle Inggris SRT/VTT.
- **Suara terlalu cepat:** ringkas teks Indonesia pada bagian yang ditandai, lalu buat ulang video.
- **Ruang disk:** unggahan, cache audio, dan hasil disimpan dalam folder proyek. Setelah aplikasi ditutup, folder proyek di `data` yang tidak dibutuhkan dapat dihapus manual.
