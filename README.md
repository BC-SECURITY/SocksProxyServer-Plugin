# SocksProxyServer-Plugin
The Socks Proxy Plugin runs a Socks Proxy Server for [Invoke-SocksProxy](https://github.com/BC-SECURITY/Invoke-SocksProxy)
that supports Socks 4 and 5 protocols. This plugin is entirely contained in [Empire](https://github.com/BC-SECURITY/Empire/)
and runs in the background. 

`socksproxyserver <start|stop> [handler port] [proxy port] [certificate] [private key]`

![image](https://user-images.githubusercontent.com/20302208/95637897-d8221480-0a47-11eb-8a69-3f132fe5d079.png)

## Getting Started
* To run the plugin, you can download it fom the releases [Releases](https://github.com/BC-SECURITY/Invoke-SocksProxy/releases) page. 

## Install
Prerequisites:
- Empire 3.5.0+

1. Add SocksServer.py to the plugins folder of Empire.

![image](https://user-images.githubusercontent.com/20302208/95636534-49f85f00-0a44-11eb-87c1-754a2368febb.png)


2. Plugins are automatically loaded into Empire as of 3.4.0, otherwise run ```plugin SocksServer```

![image](https://user-images.githubusercontent.com/20302208/95636737-b5dac780-0a44-11eb-9f82-34dcb66c24fe.png)

## Future Features
- Add multiple socks server support (similar to agents and listeners)
- Add UDP and bind request support

## Contributions
Updates made from @mjokic plugin [code](https://github.com/BC-SECURITY/Empire/pull/351)
