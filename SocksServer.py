from __future__ import print_function

from lib.common.plugins import Plugin
import lib.common.helpers as helpers
import socket
import _thread
import time
import ssl
import queue
import os
import multiprocessing


class Plugin(Plugin):
    description = "Launches a SocksProxy Server to run in the background of Empire"

    def onLoad(self):
        self.commands = {'do_socksproxyserver': {'Description': 'Launch a Socks Proxy Server',
                                           'arg': 'the argument required and it''s description'
                                           }
                         }
        self.proxy = SocksProxy()

    def execute(self, dict):
        try:
            if dict['command'] == 'do_socksproxyserver':
                results = self.do_socksproxyserver(dict['arguments']['arg'])
            return results
        except:
            return False

    def get_commands(self):
        return self.commands

    def register(self, mainMenu):
        """ any modifications to the mainMenu go here - e.g.
        registering functions to be run by user commands """
        mainMenu.__class__.do_socksproxyserver = self.do_socksproxyserver

    def do_socksproxyserver(self, line):
        "Launches a SocksProxy Server to run in the background of Empire"

        parts = line.split(' ')
        if parts[0].lower() == "kill":
            print(self.proxy.running)
            if self.proxy.running:
                self.proxy.end()
        elif not self.proxy.running:
            self.proxy.start()
        else:
            print(helpers.color("[!] SocksProxy Server Already Running!"))

    def shutdown(self):
        """if the plugin spawns a process provide a shutdown method for when Empire exits else leave it as pass"""
        if self.proxy.running:
            self.proxy.end()

class SocksProxy(object):
    def __init__(self):
        self.cert_path = os.path.abspath("./data/")
        self.cert = "%s/empire-chain.pem" % (self.cert_path)
        self.private_key = "%s/empire-priv.key" % (self.cert_path)
        if not (os.path.isfile(self.cert) and os.path.isfile(self.private_key)):
            print(helpers.color("[!] Unable to find default certificate."))

        self.handler_port = "443"
        self.proxy_port = "1080"
        self.running = False
        self.process = None


    def main(self, handler_port, proxy_port, certificate, private_key):
        _thread.start_new_thread(self.server, (handler_port, proxy_port, certificate, private_key))
        while True:
            time.sleep(60)

    def handlerServer(self, q, handler_port, certificate, private_key):
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        context.load_cert_chain(certificate, private_key)
        try:
            dock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket.bind(('', int(handler_port)))
            dock_socket.listen(5)
            print(helpers.color("\r[+] Handler listening on: " + handler_port))
            while True:
                try:
                    clear_socket, address = dock_socket.accept()
                    client_socket = context.wrap_socket(clear_socket, server_side=True)
                    try:
                        data = b""
                        while (data.count(b'\n') < 3):
                            data_recv = client_socket.recv()
                            data += data_recv
                        client_socket.send(
                            b"HTTP/1.1 200 OK\nContent-Length: 999999\nContent-Type: text/plain\nConnection: Keep-Alive\nKeep-Alive: timeout=20, max=10000\n\n")
                        q.get(False)
                    except Exception as e:
                        pass
                    q.put(client_socket)
                except Exception as e:
                    print(e)
                    pass
        except Exception as e:
            print(e)
        finally:
            dock_socket.close()

    def getActiveConnection(self, q):
        try:
            client_socket = q.get(block=True, timeout=10)
        except:
            return None
        try:
            client_socket.send(b"HELLO")
        except:
            return self.getActiveConnection(q)
        return client_socket

    def server(self, handler_port, proxy_port, certificate, private_key):
        q = queue.Queue()
        _thread.start_new_thread(self.handlerServer, (q, handler_port, certificate, private_key))
        try:
            dock_socket2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket2.bind(('127.0.0.1', int(proxy_port)))
            dock_socket2.listen(5)
            print(helpers.color("\n[+] Socks Server listening on: " + proxy_port))
            while True:
                try:
                    client_socket2, address = dock_socket2.accept()
                    client_socket = self.getActiveConnection(q)
                    if client_socket == None:
                        client_socket2.close()
                    _thread.start_new_thread(self.forward, (client_socket, client_socket2))
                    _thread.start_new_thread(self.forward, (client_socket2, client_socket))
                except Exception as e:
                    print(e)
                    pass
        except Exception as e:
            print(e)
        finally:
            dock_socket2.close()

    def forward(self, source, destination):
        try:
            string = ' '
            while string:
                string = source.recv(1024)
                if string:
                    destination.sendall(string)
                else:
                    source.shutdown(socket.SHUT_RD)
                    destination.shutdown(socket.SHUT_WR)
        except:
            try:
                source.shutdown(socket.SHUT_RD)
                destination.shutdown(socket.SHUT_WR)
            except:
                pass
            pass

    def start(self):
        print(helpers.color("[*] Starting Socks Proxy"))
        handler_port = input(helpers.color("[>] Enter Handler Port [443]: "))
        if handler_port == "":
            self.handler_port = "443"
        proxy_port = input(helpers.color("[>] Enter Proxy Port [1080]: "))
        if proxy_port == "":
            self.proxy_port = "1080"
        self.process = multiprocessing.Process(target=self.main,
                                               args=(self.handler_port, self.proxy_port, self.cert, self.private_key))
        self.running = True
        self.process.daemon = True
        self.process.start()

    def end(self):
        print(helpers.color("[!] Killing Socks Server"))
        self.running = False
        self.process.terminate()

