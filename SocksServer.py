from __future__ import print_function

from lib.common.plugins import Plugin
import lib.common.helpers as helpers
import socket
import sys
import _thread
import time
import ssl
import queue
import threading
import os

# this class MUST be named Plugin
class Plugin(Plugin):
    description = "Launches a SocksProxy Server to run in the background of Empire"

    def onLoad(self):
        """ any custom loading behavior - called by init, so any
        behavior you'd normally put in __init__ goes here """
        print("Custom loading behavior happens now.")


        self.commands = {'do_socksproxy': {'Description': 'Launch a Socks Proxy Server',
                                     'arg': 'the argument required and it''s description'
                                     }
                         }

    def execute(self, dict):
        # This is for parsing commands through the api

        try:
            # essentially switches to parse the proper command to execute
            if dict['command'] == 'do_socksproxy':
                results = self.do_socksproxy(dict['arguments']['arg'])
            return results
        except:
            return False

    def get_commands(self):
        return self.commands

    def register(self, mainMenu):
        """ any modifications to the mainMenu go here - e.g.
        registering functions to be run by user commands """
        mainMenu.__class__.do_socksproxy = self.do_socksproxy

    def do_socksproxy(self, args):
        "Launches a SocksProxy Server to run in the background of Empire"
        SocksProxy()

class SocksProxy(object):
    def __init__(self):
        cert_path = os.path.abspath("./data/")
        cert = "%s/empire-chain.pem" % (cert_path)
        private_key = "%s/empire-priv.key" % (cert_path)
        if not (os.path.isfile(cert) and os.path.isfile(private_key)):
            print(helpers.color("[!] Unable to find certpath %s, using default." % cert_path))

        handler_port = input(helpers.color("[>] Enter Handler Port [443]: "))
        if handler_port == "":
            handler_port = "443"
        proxy_port = input(helpers.color("[>] Enter Proxy Port [1080]: "))
        if proxy_port == "":
            proxy_port = "1080"

        thread = threading.Thread(target=self.main, args=(handler_port, proxy_port, cert, private_key))
        thread.daemon = True
        thread.start()

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
            print("Handler listening on: " + handler_port)
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
            print("Socks Server listening on: " + proxy_port)
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

