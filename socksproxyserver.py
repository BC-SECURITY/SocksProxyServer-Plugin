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

        q = queue.Queue()
        self.running = True
        # Both handles exist before either thread starts: on_stop joins them
        # and the accept loops compare against them.
        self.handler_thread = threading.Thread(
            target=self.handler_server,
            args=(q, self.handler_port, self.certificate, self.private_key),
            name="socks-handler",
            daemon=True,
        )
        self.server_thread = threading.Thread(
            target=self.server,
            args=(q, self.proxy_port),
            name="socks-proxy",
            daemon=True,
        )
        self.handler_thread.start()
        self.server_thread.start()

    @override
    def on_stop(self, db):
        """
        Shut down and close the listening sockets, which is what breaks the
        accept() loops out of their blocking wait, then wait for the threads.

        Empire calls on_stop for every loaded plugin at shutdown, started or
        not, so the handles may still be None here.
        """
        # Before the sockets close, so a woken loop sees the stop and exits
        # instead of spinning on an accept() that now fails immediately.
        self.running = False

        for sock in (self.proxy_socket, self.handler_socket):
            if sock is None:
                continue
            # Suppressed separately on purpose. Linux needs the shutdown() --
            # close() alone leaves accept() blocked and the port bound -- while
            # on macOS shutdown() raises ENOTCONN on a listening socket. One
            # shared suppress block would skip close() on macOS.
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()

        self.proxy_socket = None
        self.handler_socket = None

        for thread in (self.server_thread, self.handler_thread):
            # join() raises RuntimeError on a thread that was constructed but
            # never started, and that would escape into Empire's teardown loop.
            if thread is None or thread.ident is None:
                continue
            thread.join(timeout=5)
            if thread.is_alive():
                log.warning("Socks thread %s did not exit within 5s", thread.name)

        self.server_thread = None
        self.handler_thread = None

    def handler_server(self, q, handler_port, certificate, private_key):
        # Created outside the try so the finally below always has it bound.
        dock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1
            context.set_ciphers("DEFAULT@SECLEVEL=0")
            # Inside the try: these paths are operator-editable settings, so a
            # bad one is routine, and escaping this thread it would only reach
            # threading.excepthook and never land in empire_server.log.
            context.load_cert_chain(certificate, private_key)

            dock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket.bind(("", int(handler_port)))
            dock_socket.listen(5)
            self.handler_socket = dock_socket
            self.send_socketio_message("[+] Socks proxy server started")

            # self.running alone is not enough: on_stop's join is bounded, so a
            # straggler can outlive it and a following on_start sets the flag
            # back to True. on_stop nulls the handle, so the identity check is
            # what makes the old thread exit.
            while self.running and threading.current_thread() is self.handler_thread:
                try:
                    clear_socket, address = dock_socket.accept()
                    client_socket = context.wrap_socket(clear_socket, server_side=True)
                    try:
                        data = b""
                        while data.count(b"\n") < 3:
                            data_recv = client_socket.recv()
                            if not data_recv:
                                # A peer that handshakes then closes cleanly
                                # makes recv() return b'' forever, no exception.
                                raise ConnectionResetError(
                                    "peer closed before sending a request"
                                )
                            data += data_recv
                        client_socket.send(
                            b"HTTP/1.1 200 OK\nContent-Length: 999999\nContent-Type: text/plain\nConnection: Keep-Alive\nKeep-Alive: timeout=20, max=10000\n\n"
                        )
                    except Exception as e:
                        # Never park a failed request: it would evict the live
                        # agent connection below, so anyone who can reach this
                        # port could fill the queue with dead sockets.
                        log.debug("Socks handler request failed: %s", e)
                        with contextlib.suppress(OSError):
                            client_socket.close()
                        continue

                    # One connection is parked at a time; this replaces it.
                    try:
                        stale = q.get(False)
                    except queue.Empty:
                        pass
                    else:
                        with contextlib.suppress(OSError):
                            stale.close()
                    q.put(client_socket)
                except Exception as e:
                    if not self.running:
                        break
                    # Debug and no traceback: this also catches wrap_socket, so
                    # a passing scanner would otherwise write a full stack per
                    # unauthenticated probe into a non-rotating log file.
                    log.debug("Socks handler connection failed: %s", e)
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
                # Release the fd here rather than leaving it to the dropped
                # reference being collected.
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

    def server(self, q, proxy_port):
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

            # Identity check for the same reason as the handler loop above.
            while self.running and threading.current_thread() is self.server_thread:
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
            # Suppressed separately, for the same reason the listener teardown
            # in on_stop is: source.shutdown() raises ENOTCONN whenever the
            # peer has already reset, and sharing one block would then skip
            # the destination's FIN entirely -- leaving the paired relay
            # thread parked in recv() forever, holding both sockets open.
            with contextlib.suppress(Exception):
                source.shutdown(socket.SHUT_RD)
            with contextlib.suppress(Exception):
                destination.shutdown(socket.SHUT_WR)
