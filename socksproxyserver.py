import contextlib
import logging
import queue
import socket
import ssl
import threading
from typing import override

from empire.server.core.config import config_manager
from empire.server.core.plugins import BasePlugin

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    @override
    def on_load(self, db):
        self.execution_enabled = False
        # Own run flag rather than self.enabled, so the accept loops don't
        # depend on when the plugin service flips it around the lifecycle hooks.
        self.running = False
        self.handler_socket = None
        self.proxy_socket = None
        self.server_thread = None
        self.handler_thread = None
        self.settings_options = {
            "handlerport": {
                "Description": "Port number.",
                "Required": True,
                "Value": 443,
            },
            "proxyport": {
                "Description": "Port number.",
                "Required": True,
                "Value": 1080,
            },
            "certificate": {
                "Description": "Certificate directory [Default: Empire self-signed cert].",
                "Required": False,
                "Value": "",
                "Type": "file",
            },
            "privatekey": {
                "Description": "Private key directory [Default: Empire private key]",
                "Required": False,
                "Value": "",
                "Type": "file",
            },
        }

        # load default empire certs
        self.cert_path = str(config_manager.DATA_DIR / "cert")
        self.certificate = f"{self.cert_path}/empire-chain.pem"
        self.private_key = f"{self.cert_path}/empire-priv.key"
        self.handler_port = self.settings_options["handlerport"]["Value"]
        self.proxy_port = self.settings_options["proxyport"]["Value"]

    @override
    def on_start(self, db):
        settings = self.current_settings(db)
        self.handler_port = settings["handlerport"]
        self.proxy_port = settings["proxyport"]
        if settings["certificate"]:
            self.certificate = settings["certificate"]
        if settings["privatekey"]:
            self.private_key = settings["privatekey"]

        self.running = True
        self.server_thread = threading.Thread(
            target=self.server,
            args=(
                self.handler_port,
                self.proxy_port,
                self.certificate,
                self.private_key,
            ),
            daemon=True,
        )
        self.server_thread.start()

    @override
    def on_stop(self, db):
        """
        Shut down and close the listening sockets, which is what breaks the
        accept() loops out of their blocking wait, then wait for the threads.

        Empire calls on_stop for every loaded plugin at shutdown, started or
        not, so the handles may still be None here. The old implementation
        instead dialed its own ports to wake the loops, which raised
        ConnectionRefusedError whenever the server wasn't up.
        """
        # Cleared first so a woken loop sees the stop and exits instead of
        # spinning on an accept() that now fails immediately.
        self.running = False

        for sock in (self.proxy_socket, self.handler_socket):
            if sock is None:
                continue
            # shutdown() and close() are suppressed separately on purpose.
            # On Linux, close() alone does NOT wake a thread blocked in
            # accept() -- it stays blocked forever and the port stays bound,
            # so a restart fails with EADDRINUSE. shutdown() is what wakes it.
            # On macOS the reverse: shutdown() on a listening socket raises
            # ENOTCONN, but close() does wake accept(). Sharing one suppress
            # block would skip close() on macOS and break that platform.
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()

        self.proxy_socket = None
        self.handler_socket = None

        # Join before returning so the loops can't still be between their
        # accept() wake and their `while self.running` check when a following
        # on_start sets the flag back to True -- that race leaves an orphaned
        # thread spinning on a closed socket.
        for thread in (self.server_thread, self.handler_thread):
            if thread is None:
                continue
            thread.join(timeout=5)
            if thread.is_alive():
                log.warning("Socks proxy thread did not exit within 5s")

        self.server_thread = None
        self.handler_thread = None

    def handler_server(self, q, handler_port, certificate, private_key):
        # Created outside the try so the finally below always has it bound.
        dock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1
            context.set_ciphers("DEFAULT@SECLEVEL=0")
            # Inside the try: the cert/key paths are operator-editable
            # settings, so a bad path is routine. Raised out here it would
            # reach no log at all, leaving the plugin marked enabled but dead.
            context.load_cert_chain(certificate, private_key)

            dock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket.bind(("", int(handler_port)))
            dock_socket.listen(5)
            self.handler_socket = dock_socket
            self.send_socketio_message("[+] Socks proxy server started")

            while self.running:
                try:
                    clear_socket, address = dock_socket.accept()
                    client_socket = context.wrap_socket(clear_socket, server_side=True)
                    try:
                        data = b""
                        while data.count(b"\n") < 3:
                            data_recv = client_socket.recv()
                            # A peer that completes the TLS handshake and then
                            # closes cleanly makes recv() return b'' forever
                            # with no exception, so without this the loop spins
                            # at millions of iterations/sec and wedges the
                            # accept loop it runs in -- reachable by anyone who
                            # can reach this port.
                            if not data_recv:
                                break
                            data += data_recv
                        client_socket.send(
                            b"HTTP/1.1 200 OK\nContent-Length: 999999\nContent-Type: text/plain\nConnection: Keep-Alive\nKeep-Alive: timeout=20, max=10000\n\n"
                        )
                        q.get(False)
                    except queue.Empty:
                        pass
                    except Exception:
                        log.warning("Socks handler connection failed", exc_info=True)
                    q.put(client_socket)
                except Exception:
                    if not self.running:
                        break
                    log.warning("Socks handler accept failed", exc_info=True)
        except Exception as e:
            log.error("Socks handler server stopped", exc_info=True)
            self.send_socketio_message(f"[!] {e}")
        finally:
            with contextlib.suppress(OSError):
                dock_socket.close()

    def get_active_connection(self, q):
        # Discard dead connections iteratively. Recursing here meant a backlog
        # of stale sockets could exhaust the stack instead of draining.
        discarded = 0
        while True:
            try:
                client_socket = q.get(block=True, timeout=10)
            except queue.Empty:
                if discarded:
                    log.warning(
                        "Discarded %d dead agent connection(s) with none left to use",
                        discarded,
                    )
                return None

            try:
                client_socket.send(b"HELLO")
            except Exception:
                # Close it rather than leaving it to refcounting, so the fd
                # goes back immediately instead of at the next GC.
                with contextlib.suppress(Exception):
                    client_socket.close()
                discarded += 1
                continue

            if discarded:
                log.warning(
                    "Discarded %d dead agent connection(s) before finding a live one",
                    discarded,
                )
            return client_socket

    def server(self, handler_port, proxy_port, certificate, private_key):
        q = queue.Queue()
        self.handler_thread = threading.Thread(
            target=self.handler_server,
            args=(q, handler_port, certificate, private_key),
            daemon=True,
        )
        self.handler_thread.start()
        # Created outside the try so the finally below always has it bound.
        dock_socket2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            dock_socket2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket2.bind(("127.0.0.1", int(proxy_port)))
            dock_socket2.listen(5)
            self.proxy_socket = dock_socket2
            self.send_socketio_message(
                "[*] Socks server listening on: " + str(proxy_port)
            )

            while self.running:
                try:
                    client_socket2, address = dock_socket2.accept()
                    client_socket = self.get_active_connection(q)
                    if client_socket is None:
                        client_socket2.close()
                        continue
                    for pair in (
                        (client_socket, client_socket2),
                        (client_socket2, client_socket),
                    ):
                        threading.Thread(
                            target=self.forward, args=pair, daemon=True
                        ).start()
                except Exception as e:
                    # A stopping plugin wakes accept() by design, so don't
                    # report that as an error -- and break rather than loop,
                    # or the next accept() on a closed socket spins hot and
                    # floods this same channel.
                    if not self.running:
                        break
                    log.warning("Socks proxy accept failed", exc_info=True)
                    self.send_socketio_message(f"[!] Exception: {e}")
        except Exception as e:
            log.error("Socks proxy server stopped", exc_info=True)
            self.send_socketio_message(f"[!] Exception: {e}")
        finally:
            with contextlib.suppress(OSError):
                dock_socket2.close()
            self.send_socketio_message("[!] Socks proxy server stopped")

    def forward(self, source, destination):
        try:
            string = " "
            while string:
                string = source.recv(1024)
                if string:
                    destination.sendall(string)
                else:
                    source.shutdown(socket.SHUT_RD)
                    destination.shutdown(socket.SHUT_WR)
        except Exception:
            with contextlib.suppress(Exception):
                source.shutdown(socket.SHUT_RD)
                destination.shutdown(socket.SHUT_WR)
