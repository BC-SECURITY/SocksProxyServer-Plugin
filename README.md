# SocksProxyServer-Plugin
The Socks Proxy Plugin runs a Socks Proxy Server for [Invoke-SocksProxy](https://github.com/BC-SECURITY/Invoke-SocksProxy)
that supports Socks 4 and 5 protocols. This plugin is entirely contained in [Empire](https://github.com/BC-SECURITY/Empire/)
and runs in the background. 

## Getting Started
* To run the plugin, you can download it fom the releases [Releases](https://github.com/BC-SECURITY/Invoke-SocksProxy/releases) page. 

## Install
Prerequisites:
- Empire >= 4.0.0

1. Add SocksServer.py to the plugins folder of Empire.

![image](https://user-images.githubusercontent.com/20302208/120246969-b4098280-c226-11eb-9345-4ff994ee5312.png)

## Usage
### Client
![image](https://user-images.githubusercontent.com/20302208/120247213-8ffa7100-c227-11eb-8a7a-5f0de195f2e9.gif)

## Future Features
- Add multiple socks server support (similar to agents and listeners)
- Add UDP and bind request support

## Contributions
Updates made from @mjokic plugin [code](https://github.com/BC-SECURITY/Empire/pull/351)
