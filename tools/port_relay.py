"""Tiny TCP relay: 0.0.0.0:7898 -> 127.0.0.1:7897 (so WSL can use the Windows proxy)."""

from __future__ import annotations

import socket
import threading

LISTEN = ("0.0.0.0", 7898)
TARGET = ("127.0.0.1", 7897)


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(LISTEN)
    server.listen(32)
    print(f"relay {LISTEN} -> {TARGET}", flush=True)
    while True:
        client, _ = server.accept()
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            upstream.connect(TARGET)
        except OSError:
            client.close()
            continue
        threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()


if __name__ == "__main__":
    main()
