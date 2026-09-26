# Dubbing Studio untuk Windows

## Menjalankan

1. Salin `DubbingStudio.exe` ke komputer Windows 10/11 64-bit (Intel/AMD).
2. Klik dua kali. Pada awal pembukaan, tunggu komponen selesai diekstrak; ini bisa memerlukan beberapa saat.
3. Browser membuka aplikasi lokal. Biarkan jendela Dubbing Studio tetap terbuka selama pemrosesan.
4. Klik **+ Folder kursus** untuk mendaftarkan folder video, atau unggah video dari browser.
5. Pilih video lalu **Terjemahkan video** atau **Hanya Audio**.

Python, FFmpeg, FFprobe, penerjemah Inggris–Indonesia, dan komponen transkripsi sudah dibundel. Tidak perlu memasang Python atau FFmpeg, dan tidak perlu hak administrator. Siapkan sekitar 2 GB ruang kosong untuk komponen sementara, ditambah ruang untuk model, video, dan hasil.

Suara Microsoft membutuhkan internet. Model Whisper untuk video tanpa subtitle diunduh pada pemakaian pertama; ukuran bergantung pada pilihan Tiny/Base/Small. Setelah diunduh, transkripsi dan terjemahan dapat bekerja lokal. Pilihan suara Wikidepia tidak disertakan dalam EXE ini; integrasi tersebut tetap tersedia pada versi source dengan lingkungan Python terpisah.

## Hasil dan riwayat

Data disimpan di `%LOCALAPPDATA%\DubbingStudio\data`, terpisah dari EXE dan folder ekstraksi sementara. Masukkan lokasi itu pada address bar File Explorer. Hasil ada di `<id-proyek>\hasil.mp3` atau `hasil.mp4`. Log tersedia di `%LOCALAPPDATA%\DubbingStudio\logs`.

Versi EXE memulai pustaka baru. Video pribadi, hasil lama, akun, dan key Azure tidak disertakan. Proyek source lama tetap berada di folder `data` aslinya. Daftarkan kembali folder kursus yang ingin dipakai. Untuk sengaja menggunakan data source lama pada komputer yang sama, atur `DUBBING_DATA` ke lokasi folder `data` tersebut dan tutup aplikasi source terlebih dahulu; jangan jalankan dua server pada penyimpanan yang sama.

Menyalin EXE saja tidak memindahkan riwayat maupun video. Cadangkan folder data secara terpisah; folder kursus yang didaftarkan juga harus tersedia pada lokasi yang tercatat.

## Kompatibilitas

Target paket: Windows 10/11 x64. Windows 7/8, Windows 32-bit, dan ARM64 native tidak didukung oleh paket ini. Komputer harus mendukung komponen AI CTranslate2/ONNX Runtime; pengujian di komputer ini bukan jaminan untuk setiap perangkat Windows.

EXE belum ditandatangani dengan sertifikat penerbit. Windows dapat menampilkan peringatan reputasi untuk aplikasi baru; pastikan file berasal dari sumber yang Anda percayai. Tidak perlu mematikan antivirus.

## Pengembang

Build: jalankan `packaging\build_windows.ps1` dengan Python 3.13 x64 dan FFmpeg/FFprobe tersedia di PATH. Binary FFmpeg build Gyan 7.1.1 yang digunakan memiliki lisensi GPL v3; lisensi dan catatan sumber disertakan dalam bundle. Model Argos/OPUS menyertakan atribusi CC BY 4.0. Lisensi dependency lain terdapat dalam `licenses` pada bundle, dan salinannya tersedia di `build\notices`.

Pemeriksaan mandiri tanpa internet: `DubbingStudio.exe --self-test`. Laporan ditulis ke `%LOCALAPPDATA%\DubbingStudio\self-test.json`. Tambahkan `--online-test` untuk menguji suara Microsoft dan transkripsi Whisper menggunakan kalimat contoh. Ubah lokasi data melalui `DUBBING_DATA`, port awal melalui `DUBBING_PORT`, dan gunakan `--no-browser` untuk tidak membuka browser otomatis.

Referensi build: https://pyinstaller.org/en/stable/runtime-information.html dan https://opennmt.net/CTranslate2/installation.html
