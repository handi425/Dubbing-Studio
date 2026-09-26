"""Source and frozen entry point; never launch the frozen executable as Python."""
import hashlib
import json
import logging
import multiprocessing
import os
import socket
import sys
import urllib.request
import webbrowser


def main():
    if '--supertonic-worker' in sys.argv:
        from supertonic_voice import worker
        worker(sys.argv[sys.argv.index('--supertonic-worker') + 1])
        return 0
    if '--voice-worker' in sys.argv:
        from local_voice import worker
        worker(sys.argv[sys.argv.index('--voice-worker') + 1])
        return 0
    from runtime_paths import DATA, FROZEN, configure
    configure()
    logs = DATA.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, handlers=[
        RotatingFileHandler(logs / "app.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"),
        logging.StreamHandler(),
    ], format="%(asctime)s %(levelname)s %(message)s")

    if "--self-test" in sys.argv:
        from packaging_selftest import run
        return run()

    base_port = int(os.environ.get("DUBBING_PORT", "8765"))
    if not 1024 <= base_port <= 65515:
        raise ValueError("DUBBING_PORT harus antara 1024 dan 65515.")
    storage_id = hashlib.sha256(str(DATA.resolve()).casefold().encode()).hexdigest()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in range(base_port, base_port + 20):
        url = f"http://127.0.0.1:{port}"
        try:
            with opener.open(url + "/api/info", timeout=1) as response:
                existing = json.load(response)
            same = existing.get("app_id") == "dubbing-studio" and existing.get("storage_id") == storage_id
            legacy = not FROZEN and "id-ID-ArdiNeural" in existing.get("voices", {}) and "storage_id" not in existing
            if same or legacy:
                if "--no-browser" not in sys.argv:
                    webbrowser.open(url)
                print(f"Dubbing Studio sudah berjalan: {url}", flush=True)
                return 0
        except (OSError, ValueError):
            pass
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
        break
    else:
        raise RuntimeError("Port aplikasi sedang digunakan. Tutup instance lama atau ubah DUBBING_PORT.")

    import app
    from waitress import create_server
    server = create_server(app.app, host="127.0.0.1", port=port, threads=6,
                           max_request_body_size=app.app.config["MAX_CONTENT_LENGTH"])
    print(f"\nDubbing Studio siap: {url}\nHasil dan riwayat: {DATA}\n"
          "Biarkan jendela ini terbuka selama pemrosesan.\n"
          "Tutup setelah pekerjaan selesai, atau tekan Ctrl+C untuk berhenti.\n", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        with app.lock:
            app.cancelled.update(jid for jid, job in app.jobs.items() if job["status"] in app.ACTIVE)
        server.close()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Dubbing Studio gagal dibuka")
        if sys.stdin and sys.stdin.isatty() and "--no-browser" not in sys.argv and "--self-test" not in sys.argv:
            input("Tekan Enter untuk menutup. Detail tersedia di folder logs. ")
        sys.exit(1)
