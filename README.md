# SocksProxyServer-Plugin
The Socks Proxy Plugin runs a Socks Proxy Server for [Invoke-SocksProxy](https://github.com/BC-SECURITY/Invoke-SocksProxy)
that supports Socks 4 and 5 protocols. This plugin is entirely contained in [Empire](https://github.com/BC-SECURITY/Empire/)
and runs in the background. 



## Install
Prerequisites:
- Empire >= 6.0

1. Install from the Marketplace 

![image](https://github.com/user-attachments/assets/0cc5ef26-4cac-4533-bebf-8f9ceb37220c)


## Usage
### Client
1. Once installed from the Marketplace go to the settings tab of the plugin
   ![image](https://github.com/user-attachments/assets/5235bfa4-6a20-4fe5-a42a-8cea4afa0633)

2. The ports default to 443 for listening for an external connection and 1080 for use by proxychains 

## Future Features
- Add multiple socks server support (similar to agents and listeners)
- Add UDP and bind request support

## Contributions
Updates made from @mjokic plugin [code](https://github.com/BC-SECURITY/Empire/pull/351)
