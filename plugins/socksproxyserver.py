from __future__ import print_function

from empire.server.common.plugins import Plugin
from empire.server.common.empire import MainMenu

import socket
import _thread
import ssl
import queue
import os


class Plugin(Plugin):
    description = "Launches a Socks Proxy Server to run in the background of Empire"

    def onLoad(self):
        """ any custom loading behavior - called by init, so any
        behavior you'd normally put in __init__ goes here """
        self.info = {
                        'Name': 'socksproxyserver',

                        'Author': ['@Cx01N', '@mjokic'],

                        'Description': ('Launches a Socks Proxy Server to run in the background of Empire.'),

                        'Software': '',

                        'Techniques': [''],

                        'Comments': []
                    },

        self.options = {
                    'status': {
                        'Description': 'Start/stop the Chisel server. Specify a port or default to 8080.',
                        'Required': True,
                        'Value': 'start'
                    },
                    'handlerport': {
                        'Description': 'Port number.',
                        'Required': True,
                        'Value': '443'
                    },
                    'proxyport': {
                        'Description': 'Port number.',
                        'Required': True,
                        'Value': '1080'
                    },
                    'certificate': {
                        'Description': 'Certifcate directory [Default: Empire self-signed cert].',
                        'Required': False,
                        'Value': ''
                    },
                    'privatekey': {
                        'Description': 'Private key directory [Default: Empire private key]',
                        'Required': False,
                        'Value': ''
                    },
        }


        # load default empire certs
        self.cert_path = os.path.abspath("./empire/server/data/")
        self.certificate = "%s/empire-chain.pem" % self.cert_path
        self.private_key = "%s/empire-priv.key" % self.cert_path

        self.running = False

    def execute(self, command):
        # This is for parsing commands through the api
        try:
            # essentially switches to parse the proper command to execute
            self.options['status']['Value'] = command['status']
            self.options['handlerport']['Value'] = command['handlerport']
            self.options['proxyport']['Value'] = command['proxyport']
            self.options['certificate']['Value'] = command['certificate']
            self.options['privatekey']['Value'] = command['privatekey']
            results = self.do_socksproxyserver('')
            return results
        except:
            return False

    def get_commands(self):
        return self.commands

    def register(self, main_menu):
        """ any modifications to the main_menu go here - e.g.
        registering functions to be run by user commands """
        main_menu.__class__.do_socksproxyserver = self.do_socksproxyserver

    def do_socksproxyserver(self, args):
        "Launches a SocksProxy Server to run in the background of Empire"

        if not args:
            # Load defaults for server
            self.status = self.options['status']['Value']
            self.handler_port = self.options['handlerport']['Value']
            self.proxy_port = self.options['proxyport']['Value']

            if not self.options['certificate']['Value'] or self.options['privatekey']['Value']:
                # load default empire certs
                self.cert_path = os.path.abspath("./empire/server/data/")
                self.certificate = "%s/empire-chain.pem" % self.cert_path
                self.private_key = "%s/empire-priv.key" % self.cert_path

        else:
            args = args.split(" ")

            # Check server status
            if args[0].lower() == "start":
                self.status = 'start'
            elif args[0].lower() == "stop":
                self.status = 'stop'
            # Check for port numbers
            if len(args) > 2:
                self.handler_port = args[1]
                self.proxy_port = args[2]
            else:
                self.handler_port = self.options['handlerport']['Value']
                self.proxy_port = self.options['proxyport']['Value']

            # Check for certificates
            if len(args) > 4:
                self.certificate = args[3]
                self.private_key = args[4]
            else:
                # load default empire certs
                self.cert_path = os.path.abspath("./empire/server/data/")
                self.certificate = "%s/empire-chain.pem" % self.cert_path
                self.private_key = "%s/empire-priv.key" % self.cert_path

        # Switch for starting and stopping server
        if self.status == "start":
            self.start_socks_server()
        elif self.status == "stop":
            self.shutdown()
        else:
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[!] Usage: socksserver <start|stop> [handler port] [proxy port] [certificate] [private key]")

    def start_socks_server(self):
        if not self.running:
            self.running = True
            _thread.start_new_thread(self.server,
                                     (self.handler_port, self.proxy_port, self.certificate, self.private_key))
        else:
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[!] Socks Proxy Server Already Running!")

    def shutdown(self):
        """if the plugin spawns a process provide a shutdown method for when Empire exits else leave it as pass"""
        if self.running:
            self.running = False
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[*] Stopping socks proxy server...")
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", int(self.handler_port)))
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", int(self.proxy_port)))
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[+] Socks proxy server stopped")
        else:
            MainMenu.send_socketio_message(self,f'plugin/{self.info[0]["Name"]}/notifications', "[!] Server is not running!")

    def handler_server(self, q, handler_port, certificate, private_key):
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        context.load_cert_chain(certificate, private_key)
        try:
            dock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket.bind(('', int(handler_port)))
            dock_socket.listen(5)
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[+] Socks proxy server started")

            while self.running:
                try:
                    clear_socket, address = dock_socket.accept()
                    client_socket = context.wrap_socket(clear_socket, server_side=True)
                    try:
                        data = b""
                        while data.count(b'\n') < 3:
                            data_recv = client_socket.recv()
                            data += data_recv
                        client_socket.send(
                            b"HTTP/1.1 200 OK\nContent-Length: 999999\nContent-Type: text/plain\nConnection: Keep-Alive\nKeep-Alive: timeout=20, max=10000\n\n")
                        q.get(False)
                    except Exception as e:
                        pass
                    q.put(client_socket)
                except Exception as e:
                    pass
        except Exception as e:
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[!] " + e.strerror)
        finally:
            dock_socket.close()

    def get_active_connection(self, q):
        try:
            client_socket = q.get(block=True, timeout=10)
        except:
            return None
        try:
            client_socket.send(b"HELLO")
        except:
            return self.get_active_connection(q)
        return client_socket

    def server(self, handler_port, proxy_port, certificate, private_key):
        q = queue.Queue()
        _thread.start_new_thread(self.handler_server, (q, handler_port, certificate, private_key))
        try:
            dock_socket2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dock_socket2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            dock_socket2.bind(('127.0.0.1', int(proxy_port)))
            dock_socket2.listen(5)
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[*] Socks server listening on: " + proxy_port)

            while self.running:
                try:
                    client_socket2, address = dock_socket2.accept()
                    client_socket = self.get_active_connection(q)
                    if client_socket == None:
                        client_socket2.close()
                    _thread.start_new_thread(self.forward, (client_socket, client_socket2))
                    _thread.start_new_thread(self.forward, (client_socket2, client_socket))
                except Exception as e:
                    MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications',
                                                   "[!] Exception: %s" % e)
        except Exception as e:
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications',
                                           "[!] Exception: %s" % e)
        finally:
            dock_socket2.close()
            MainMenu.send_socketio_message(self, f'plugin/{self.info[0]["Name"]}/notifications', "[+] Socks proxy server stopped")

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
