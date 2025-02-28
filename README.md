<!--
 * @Author: kemomi 
 * @Date: 2025-02-28 23:43:59
 * @LastEditors: kemomi 
 * @LastEditTime: 2025-02-28 23:56:46
 * @FilePath: \RaspberryPi-xiaozhi\README.md
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
# 介绍
在树莓派上部署小智可以最大化利用闲置树莓派3b+/4b/5，丰富的接口便于扩展，
使用python脚本即可部署，添加gpio引脚开关非常方便开启对话模式，开机自动运行。

## 小智项目地址
https://github.com/78/xiaozhi-esp32
## 小智项目教程文档
https://ccnphfhqs21z.feishu.cn/wiki/F5krwD16viZoF0kKkvDcrZNYnhb
## 飞书文档
https://ccnphfhqs21z.feishu.cn/wiki/EH6wwrgvNiU7aykr7HgclP09nCh （附配件链接）
## 服务端开源地址
https://github.com/xinnan-tech/xiaozhi-esp32-server

# 第一版本
安装必要要的库比如opuslib
gpio17(11引脚)连接开关
把程序命名为xiaozhi.py后放在/home/pi目录下
设置开机启动
1. 创建 autostart 目录（如果没有的话）
首先，确保 ~/.config/autostart/ 目录存在。如果没有该目录，可以手动创建它：
   mkdir -p ~/.config/autostart
2. 创建 .desktop 文件在 autostart 目录中，为你的程序创建一个 .desktop 文件。这是一个文本文件，告诉系统在用户登录时如何启动程序。创建一个名为 xiaozhi.desktop 的文件：
   nano ~/.config/autostart/xiaozhi.desktop
然后，在文件中添加以下内容：

[Desktop Entry]
Name=XiaoZhi
Exec=python3 /home/pi/xiaozhi.py
Type=Application
X-GNOME-Autostart-enabled=true
Comment=Run xiaozhi.py at startup

5. 设置权限
确保 .desktop 文件具有执行权限：
 sudo chmod +x ~/.config/autostart/xiaozhi.desktop

# 第二版本
 保持会话
 
# 第三版本