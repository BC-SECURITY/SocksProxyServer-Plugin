import _thread
import queue
import socket
import ssl
from typing import override

from empire.server.core.config import config_manager
from empire.server.core.plugins import BasePlugin


class Plugin(BasePlugin):
    @override
    def on_load(self, db):
        self.execution_enabled = False
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

        _thread.start_new_thread(
            self.server,
            (
                self.handler_port,
                self.proxy_port,
                self.certificate,
                self.private_key,
            ),
        )

    def on_stop(self, db):
        """
        if the plugin spawns a process provide a shutdown method for when Empire exits else leave it as pass
        """
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("127.0.0.1", int(self.handler_port))
        )
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("127.0.0.1", int(self.proxy_port))
        )

    def handler_server(self, q, handler_port, certificate, private_key):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1
        context.set_ciphers("DEFAULT@SECLEVEL=0")
        context.load_cert_chain(certificate, private_key)
        try:
            dock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket.bind(("", int(handler_port)))
            dock_socket.listen(5)
            self.send_socketio_message("[+] Socks proxy server started")

            while self.enabled:
                try:
                    clear_socket, address = dock_socket.accept()
                    client_socket = context.wrap_socket(clear_socket, server_side=True)
                    try:
                        data = b""
                        while data.count(b"\n") < 3:
                            data_recv = client_socket.recv()
                            data += data_recv
                        client_socket.send(
                            b"HTTP/1.1 200 OK\nContent-Length: 999999\nContent-Type: text/plain\nConnection: Keep-Alive\nKeep-Alive: timeout=20, max=10000\n\n"
                        )
                        q.get(False)
                    except Exception:
                        pass
                    q.put(client_socket)
                except Exception:
                    pass
        except Exception as e:
            self.send_socketio_message("[!] " + e.strerror)
        finally:
            dock_socket.close()

    def get_active_connection(self, q):
        try:
            client_socket = q.get(block=True, timeout=10)
        except Exception:
            return None
        try:
            client_socket.send(b"HELLO")
        except Exception:
            return self.get_active_connection(q)
        return client_socket

    def server(self, handler_port, proxy_port, certificate, private_key):
        q = queue.Queue()
        _thread.start_new_thread(
            self.handler_server, (q, handler_port, certificate, private_key)
        )
        try:
            dock_socket2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket2.bind(("127.0.0.1", int(proxy_port)))
            dock_socket2.listen(5)
            self.send_socketio_message("[*] Socks server listening on: " + proxy_port)

            while self.enabled:
                try:
                    client_socket2, address = dock_socket2.accept()
                    client_socket = self.get_active_connection(q)
                    if client_socket is None:
                        client_socket2.close()
                    _thread.start_new_thread(
                        self.forward, (client_socket, client_socket2)
                    )
                    _thread.start_new_thread(
                        self.forward, (client_socket2, client_socket)
                    )
                except Exception as e:
                    self.send_socketio_message(f"[!] Exception: {e}")
        except Exception as e:
            self.send_socketio_message(f"[!] Exception: {e}")
        finally:
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
            try:
                source.shutdown(socket.SHUT_RD)
                destination.shutdown(socket.SHUT_WR)
            except Exception:
                pass
            pass
