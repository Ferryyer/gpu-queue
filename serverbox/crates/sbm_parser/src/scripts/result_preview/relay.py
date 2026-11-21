"""Raw HTTP byte stream inside the authenticated user's execution namespace."""
import os
import socket
import sys
import threading


def relay(path):
    remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    remote.settimeout(10)
    remote.connect(path)
    remote.settimeout(None)

    def upload():
        try:
            while True:
                data = os.read(0, 65536)
                if not data:
                    break
                remote.sendall(data)
        except OSError:
            pass
        finally:
            try:
                remote.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    threading.Thread(target=upload, daemon=True).start()
    try:
        while True:
            data = remote.recv(65536)
            if not data:
                break
            remaining = memoryview(data)
            while remaining:
                remaining = remaining[os.write(1, remaining):]
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        remote.close()


if __name__ == '__main__':
    relay(sys.argv[1] if len(sys.argv) == 2 else f'/tmp/fileshare-{os.getuid()}/web.sock')
