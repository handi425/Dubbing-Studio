# Dubbing Studio

[Unduh EXE Windows terbaru](https://github.com/handi425/Dubbing-Studio/releases/latest)

History kini berupa tabel dengan pilihan lintas halaman, Play, Unduh, dan hapus massal. Buat playlist hasil dari History untuk ditonton di halaman Playlist video; tersedia Play semua berurutan dan Unduh semua dalam satu ZIP. Perbaikan grammar AI dapat dijalankan sekaligus dengan pratinjau dan urungkan.

Versi Windows `.exe`: lihat [WINDOWS-EXE.md](WINDOWS-EXE.md). File distribusi
`dist/DubbingStudio.exe` membundel Python, FFmpeg, dan penerjemah lokal untuk
Windows 10/11 x64. Build ulang melalui `packaging/build_windows.ps1`.

Aplikasi lokal Windows untuk menerjemahkan video Inggris dan membuat sulih suara AI dengan 10 preset Supertonic 3 dan 30 pilihan bahasa. Sintesis suara dan terjemahan lokal berjalan di CPU tanpa API; model bahasa tambahan diunduh saat pertama kali dipilih.

## Video demo

Demonstrasi penggunaan Dubbing Studio (1 menit 43 detik). Klik tombol putar untuk menonton langsung.

https://github.com/user-attachments/assets/dd0d5b8c-c99e-4b67-97eb-e1315e2b1b82

[Unduh video demo MP4](https://github.com/handi425/Dubbing-Studio/raw/refs/heads/main/docs/dubbing-studio-demo.mp4)

## Menjalankan

Klik dua kali **MULAI DUBBING.bat** pada folder aplikasi. Aplikasi terbuka di http://127.0.0.1:8765. Biarkan jendela server berjalan selama pemrosesan. Instalasi pertama memerlukan internet. Python 3.11–3.13 dan FFmpeg/FFprobe harus ada di PATH.

1. Pilih satu atau beberapa video dari pustaka kursus, atau unggah beberapa video sekaligus (total unggahan kurang dari 8 GB). Pilihan **Pilih semua hasil** mengikuti pencarian; **Hapus pilihan** mengosongkan pilihan pustaka.
2. Pilih model suara, bahasa dubbing, kecepatan, dan volume suara asli dari dropdown.
3. Klik **Terjemahkan video** untuk hasil MP4, atau **Hanya Audio** di bawahnya untuk sulih suara Indonesia dalam MP3 sesuai bahasa dubbing yang dipilih. Subtitle `.vtt`/`.srt` yang cocok dipakai otomatis, termasuk penamaan `CHP 1 ...` pada kursus ini. Subtitle Inggris manual tersedia untuk pilihan satu video.
4. Tanpa subtitle, Whisper mentranskripsi bahasa Inggris di CPU lokal. Model diunduh pada pemakaian pertama; proses dapat lambat pada video panjang.
5. Untuk satu video, periksa dan edit terjemahan, lalu klik **Buat video dubbing** atau **Buat audio dubbing**. Untuk beberapa video, setiap video diterjemahkan dan dibuat sulih suaranya secara otomatis, berurutan sampai selesai.
6. Pantau status setiap video pada **Antrean video**. Putar atau unduh hasil MP4/MP3 masing-masing, subtitle sesuai bahasa keluaran dan Inggris, serta transkrip. Klik proyek untuk mengedit terjemahan, membuat ulang hasil, membatalkan, atau mencoba kembali; kegagalan satu video tidak menghentikan video berikutnya.

Mode **Hanya Audio** menyimpan `data/<id-proyek>/hasil.mp3`, tanpa membuat video baru. Bahasa, pengaturan suara, kecepatan, dan volume suara asli juga berlaku untuk MP3.

Hasil berada di `DubbingStudio/data/<id-proyek>/hasil.mp4`. Video asli tidak diubah. Riwayat proyek tetap tersedia setelah aplikasi ditutup. Proses berjalan satu per satu; tombol batalkan menunggu operasi jaringan/model yang sedang berjalan selesai. Setelah gangguan, klik **Lanjutkan / coba lagi**. Cache terjemahan dan audio dipakai kembali. Pada proses transkripsi yang terputus, transkripsi dimulai lagi.

## Pustaka paket / playlist kursus

Tab **Pustaka kursus** menampilkan paket kursus yang pernah dimuat. Pilih playlist untuk melihat video menurut bab/subfolder. Pencarian paket terpisah dari pencarian video; **Pilih semua hasil** hanya memilih video dalam playlist dan pencarian saat ini. Berpindah playlist mengosongkan pilihan video agar kursus tidak tercampur.

Untuk menambah kursus, klik **+ Folder kursus** atau buka **Unggah video**:

- **Daftarkan folder:** masukkan lokasi lengkap, misalnya `D:\Kursus\Nama Kursus`, lalu klik **Daftarkan folder**. Semua subfolder dipindai. Video tetap di lokasi asal sehingga cara ini sesuai untuk koleksi besar dan tidak menyalin file. Folder/drive asal harus tersedia saat pemrosesan.
- **Unggah folder:** pilih folder kursus, periksa jumlah video yang terdeteksi, lalu klik **Simpan sebagai playlist**. Aplikasi menyalin video dan subtitle ke penyimpanan lokal satu file per giliran. Batas unggahan 8 GB berlaku per file; total kursus dapat lebih besar. Untuk file 8 GB atau lebih, gunakan **Daftarkan folder**.

Format video yang dikenali: MP4, MKV, MOV, WEBM, AVI, M4V (termasuk ekstensi huruf besar). File lain dilewati, kecuali subtitle SRT/VTT. Nama video yang sama di bab berbeda tetap terpisah. Urutan nama menggunakan angka secara alami, sehingga pelajaran 2 mendahului pelajaran 10. Subtitle dengan nama yang cocok dipakai otomatis.

Playlist tersimpan di `data/playlists/<id>/playlist.json`; salinan unggahan di subfolder `media`. Playlist tetap ada setelah browser/server ditutup, dan browser mengingat playlist terakhir. Pustaka lama tetap muncul sebagai playlist pertama. Klik **Pindai ulang** setelah menambah atau memindahkan video dalam folder yang terdaftar. Mendaftarkan lokasi folder yang sama memperbarui playlist yang sudah ada.

Jika unggahan terputus atau dihentikan, playlist ditandai **Impor belum selesai**. Klik playlist tersebut, pilih kembali folder yang sama, lalu lanjutkan impor. File yang sudah tersimpan diperbarui pada lokasi yang sama tanpa menggandakan video. Pemrosesan dubbing tersedia setelah impor selesai. Jika folder lokal dipindah atau drive dilepas, aplikasi menampilkan keterangan folder tidak tersedia.

Impor folder hanya membangun pustaka. Pilih video lalu klik **Terjemahkan video** atau **Hanya Audio** untuk memulai pemrosesan.

## Layanan dan koneksi

- Suara default memakai **Supertonic 3**, berjalan lokal di CPU melalui ONNX. Urutan pilihan awal pada instalasi source adalah Supertonic, Wikidepia ONNX, lalu Microsoft Edge sesuai ketersediaan model. Mesin selalu ditampilkan pada Pengaturan layanan; pilihan lokal yang gagal tidak otomatis dialihkan ke layanan online.
- Microsoft Edge tetap tersedia melalui [edge-tts](https://github.com/rany2/edge-tts), pustaka pihak ketiga, tanpa API key tetapi membutuhkan internet. Ini bukan SDK Azure resmi dan ketersediaannya dapat berubah.
- Terjemahan default memakai model Inggris–Indonesia [Argos](https://github.com/argosopentech/argospm-index) melalui CTranslate2 di komputer. Model sekitar 65 MB diunduh sekali, kemudian dapat dipakai offline.
- Google web dan Microsoft Translator tersedia sebagai pilihan penerjemah online. Google web bukan Cloud Translation API resmi; layanan ini menolak permintaan saat pengujian, sehingga bukan pilihan utama.
- Video tetap di komputer. Dengan penerjemah dan suara lokal, teks tetap lokal. **Untuk suara Microsoft, teks Indonesia dikirim ke Microsoft.** Bila memilih penerjemah online, teks Inggris juga dikirim ke layanan itu. Antarmuka memakai font sistem tanpa unduhan font.
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

## Supertonic 3: suara AI offline bawaan

Pilih **Supertonic 3 · offline tanpa API**. Sepuluh preset M1–M5 dan F1–F5 serta 30 pilihan bahasa memakai model lokal; model penerjemah offline untuk bahasa tambahan diunduh satu kali saat bahasa tersebut pertama dipakai. Kode penerjemah Indonesia tetap dibundel. Pengaturan kecepatan, cache, antrean, pembatalan, dan hasil MP3/MP4 tetap tersedia.

Menu **Pengaturan AI** dapat menyimpan API key OpenRouter dan memilih router/model gratis. Windows mengenkripsi key untuk profil pengguna lokal. Tombol **Perbaiki dengan AI** merapikan teks per kalimat; teks tersebut dikirim ke model OpenRouter yang dipilih, jadi fitur itu memerlukan internet. Penggunaan model gratis mengikuti ketersediaan dan batas OpenRouter. Menu samping membuka riwayat proyek dan playlist; tombol Hapus menghapus data proyek atau playlist unggahan aplikasi. Playlist folder lokal hanya menghapus entri, bukan berkas video sumber.

Model resmi Supertonic sekitar **380 MiB / 399 MB** dibundel dalam EXE. Sepuluh file preset suara menambah aset kecil. Ukuran ini hanya model, bukan seluruh aplikasi atau kebutuhan RAM. Pemrosesan memakai ONNX Runtime CPU dengan maksimum 4 thread per sesi, tanpa PyTorch atau GPU. Teks panjang dipotong dan disimpan bertahap; proses model ditutup sesudah batch agar RAM dilepas. Sintesis suara tidak memakai layanan TTS atau API. Model terjemahan bahasa tambahan perlu diunduh sekali saat pertama digunakan.

Gunakan penerjemah **Lokal di komputer**. Untuk bahasa Indonesia, subtitle Inggris dapat diterjemahkan dan di-dubbing offline sejak awal. Untuk bahasa lain, model Argos langsung Inggris-ke-bahasa target diunduh otomatis saat pertama dipakai. Tanpa subtitle, unduh model Whisper sekali terlebih dahulu.

Untuk menjalankan source, klik **PASANG SUPERTONIC.bat** sekali dengan koneksi internet, lalu **MULAI DUBBING.bat**. Skrip mengambil aset dari arsip resmi pada revisi tetap, memeriksa ukuran dan hash SHA-256 model, lalu menyimpannya di `data/models/supertonic-3`. EXE sudah membawa aset tersebut dan tidak membutuhkan pemasangan ini.

Kode inferensi resmi disimpan di `third_party/supertonic` dengan lisensi MIT. Model memakai **OpenRAIL-M**; ketentuan lengkap dan pembatasan penggunaan ada dalam LICENSE yang disertakan bersama model. Repositori upstream diarsipkan pada September 2026; integrasi memakai snapshot tetap, bukan layanan hosted.

Sumber: [kode resmi](https://github.com/supertone-oss-archive/supertonic), [model dan lisensi](https://huggingface.co/supertone-oss-archive/supertonic-3).

## Wikidepia ONNX (opsional pada source)

Pilihan **Wikidepia ONNX · offline (opsional)** memakai model sekitar 116 MiB dengan suara Ardi/Gadis. Model ini tidak dibundel dalam EXE Supertonic agar ukuran paket tidak bertambah. Model Wikidepia dibatasi upstream untuk penggunaan **nonkomersial**.

Untuk pengembang yang ingin menyiapkannya, pasang lingkungan lama melalui `PASANG SUARA LOKAL.bat`, lalu jalankan:

```powershell
.\.venv\Scripts\python.exe -m pip --python .venv-drat\Scripts\python.exe install "onnx>=1.16,<2"
.\.venv-drat\Scripts\python.exe -X utf8 export_local_voice.py
```

PyTorch/Coqui hanya diperlukan saat konversi. Model hasil berada di `data/models/voice-onnx`. Referensi: [Coqui VITS ONNX](https://docs.coqui.ai/en/dev/models/vits.html).

## Suara Wikidepia versi pengembangan (PyTorch)

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
