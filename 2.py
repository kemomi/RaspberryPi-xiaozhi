#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import time
import requests
import paho.mqtt.client as mqtt
import paho.mqtt.subscribe as subscribe
import paho.mqtt.publish as publish
import threading
import pyaudio
import opuslib
import socket
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import logging
import RPi.GPIO as GPIO
from tkinter import Tk, scrolledtext, Frame, END
from tkinter.font import Font
import queue
import os
os.environ['DISPLAY'] = ':0'
os.environ['XAUTHORITY'] = '/home/pi/.Xauthority'

# 设置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='app.log',
    filemode='w'
)

# ============ GPIO配置 ==============
BUTTON_PIN = 16
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ============ 全局变量 ==============
OTA_VERSION_URL = 'https://api.tenclass.net/xiaozhi/ota/'
MAC_ADDR = 'xx:xx:xx:2d:b4:ba' # 修改这里改一个不一样的

mqtt_info = {}
aes_opus_info = {
    "type": "hello",
    "version": 3,
    "transport": "udp",
    "udp": {
        "server": "120.24.160.13",
        "port": 8884,
        "encryption": "aes-128-ctr",
        "key": "263094c3aa28cb42f3965a1020cb21a7",
        "nonce": "01000000ccba9720b4bc268100000000"
    },
    "audio_params": {
        "format": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "frame_duration": 60
    },
    "session_id": "b23ebfe9"
}

iot_msg = {"session_id": "635aa42d", "type": "iot",
           "descriptors": [{"name": "Speaker", "description": "当前 AI 机器人的扬声器",
                            "properties": {"volume": {"description": "当前音量值", "type": "number"}},
                            "methods": {"SetVolume": {"description": "设置音量",
                                                      "parameters": {
                                                          "volume": {"description": "0到100之间的整数", "type": "number"}
                                                      }
                                                      }
                                        }
                            },
                           {"name": "Lamp", "description": "一个测试用的灯",
                            "properties": {"power": {"description": "灯是否打开", "type": "boolean"}},
                            "methods": {"TurnOn": {"description": "打开灯", "parameters": {}},
                                        "TurnOff": {"description": "关闭灯", "parameters": {}}
                                        }
                            }
                           ]
           }

iot_status_msg = {
    "session_id": "635aa42d",
    "type": "iot",
    "states": [
        {"name": "Speaker", "state": {"volume": 50}},
        {"name": "Lamp", "state": {"power": False}}
    ]
}

goodbye_msg = {
    "session_id": "b23ebfe9",
    "type": "goodbye"
}

local_sequence = 0
listen_state = None
tts_state = None
key_state = None
audio = None
udp_socket = None
conn_state = False
running = True
last_heartbeat = 0
last_listen_stop_time = None  # 新增变量，记录最后一次停止监听的时间

# 线程管理
recv_audio_thread = None
send_audio_thread = None
mqtt_client = None

# ============ 新增全局变量 ==============
GUI_UPDATE_QUEUE = queue.Queue()
RECONNECT_INTERVAL = 5  # 每5秒重连一次
HEARTBEAT_INTERVAL = 30  # 每30秒发送一次心跳

# ============ GUI配置 ==============
class ChatWindow:
    def __init__(self, master):
        self.master = master
        master.title("聊天中")
        master.geometry("800x600")

        # 适配树莓派触摸屏
        master.attributes('-fullscreen', True)
        master.bind("<Escape>", lambda e: master.attributes('-fullscreen', False))

        # 创建大字体
        self.custom_font = Font(family="WenQuanYi Zen Hei", size=124)

        # 创建滚动区域
        frame = Frame(master)
        frame.pack(expand=True, fill="both")

        # 滚动文本框
        self.text_area = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            font=self.custom_font,
            state='disabled',
            padx=20,
            pady=20
        )
        self.text_area.pack(expand=True, fill="both")

        # 标签样式
        self.text_area.tag_config("user", foreground="blue")
        self.text_area.tag_config("system", foreground="green")
        self.text_area.tag_config("error", foreground="red")

        # 定期检查更新队列
        self.check_queue()

    def check_queue(self):
        while not GUI_UPDATE_QUEUE.empty():
            text, tag = GUI_UPDATE_QUEUE.get()
            self._add_message(text, tag)
        self.master.after(100, self.check_queue)

    def _add_message(self, text, tag=None):
        self.text_area.configure(state='normal')
        self.text_area.insert(END, text + "\n", tag)
        self.text_area.configure(state='disabled')
        self.text_area.see(END)

def get_ota_version():
    global mqtt_info
    header = {
        'Device-Id': MAC_ADDR,
        'Content-Type': 'application/json'
    }
    post_data = {
        "flash_size": 16777216,
        "minimum_free_heap_size": 8318916,
        "mac_address": f"{MAC_ADDR}",
        "chip_model_name": "esp32s3",
        "chip_info": {"model": 9, "cores": 2, "revision": 2, "features": 18},
        "application": {
            "name": "xiaozhi",
            "version": "0.9.9",
            "compile_time": "Jan 22 2025T20:40:23Z",
            "idf_version": "v5.3.2-dirty",
            "elf_sha256": "22986216df095587c42f8aeb06b239781c68ad8df80321e260556da7fcf5f522"
        },
        "partition_table": [
            {"label": "nvs", "type": 1, "subtype": 2, "address": 36864, "size": 16384},
            {"label": "otadata", "type": 1, "subtype": 0, "address": 53248, "size": 8192},
            {"label": "phy_init", "type": 1, "subtype": 1, "address": 61440, "size": 4096},
            {"label": "model", "type": 1, "subtype": 130, "address": 65536, "size": 983040},
            {"label": "storage", "type": 1, "subtype": 130, "address": 1048576, "size": 1048576},
            {"label": "factory", "type": 0, "subtype": 0, "address": 2097152, "size": 4194304},
            {"label": "ota_0", "type": 0, "subtype": 16, "address": 6291456, "size": 4194304},
            {"label": "ota_1", "type": 0, "subtype": 17, "address": 10485760, "size": 4194304}
        ],
        "ota": {"label": "factory"},
        "board": {
            "type": "bread-compact-wifi",
            "ssid": "mzy",
            "rssi": -58,
            "channel": 6,
            "ip": "192.168.124.38",
            "mac": "cc:ba:97:20:b4:bc"
        }
    }

    try:
        response = requests.post(OTA_VERSION_URL, headers=header, data=json.dumps(post_data), timeout=10)
        response.raise_for_status()
        mqtt_info = response.json()['mqtt']
        GUI_UPDATE_QUEUE.put(("配置更新成功", "system"))
        logging.info("配置更新成功")
    except Exception as e:
        GUI_UPDATE_QUEUE.put((f"配置更新失败: {str(e)}", "error"))
        logging.error(f"配置更新失败: {str(e)}")
        time.sleep(RECONNECT_INTERVAL)
        get_ota_version()

def aes_ctr_encrypt(key, nonce, plaintext):
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()

def aes_ctr_decrypt(key, nonce, ciphertext):
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext

def send_audio():
    global aes_opus_info, udp_socket, local_sequence, listen_state, audio, running
    key = aes_opus_info['udp']['key']
    nonce = aes_opus_info['udp']['nonce']
    server_ip = aes_opus_info['udp']['server']
    server_port = aes_opus_info['udp']['port']

    encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)
    mic = audio.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=960)

    try:
        while running and aes_opus_info['session_id']:
            if listen_state == "stop":
                time.sleep(0.1)
                continue

            data = mic.read(960)
            encoded_data = encoder.encode(data, 960)

            local_sequence += 1
            new_nonce = nonce[0:4] + format(len(encoded_data), '04x') + nonce[8:24] + format(local_sequence, '08x')

            encrypt_encoded_data = aes_ctr_encrypt(
                bytes.fromhex(key),
                bytes.fromhex(new_nonce),
                bytes(encoded_data)
            )
            data = bytes.fromhex(new_nonce) + encrypt_encoded_data
            try:
                udp_socket.sendto(data, (server_ip, server_port))
            except socket.error as e:
                if e.errno == errno.ENETUNREACH:
                    # 网络不可达，尝试重新连接或处理
                    restart_audio_streams()
                    break
                else:
                    raise
    except Exception as e:
        logging.error(f"音频发送错误: {str(e)}")
    finally:
        mic.stop_stream()
        mic.close()

def recv_audio():
    global aes_opus_info, udp_socket, audio, running
    key = aes_opus_info['udp']['key']
    sample_rate = aes_opus_info['audio_params']['sample_rate']
    frame_duration = aes_opus_info['audio_params']['frame_duration']
    frame_num = int(frame_duration / (1000 / sample_rate))

    decoder = opuslib.Decoder(sample_rate, 1)
    spk = audio.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True, frames_per_buffer=frame_num)

    try:
        while running and aes_opus_info['session_id']:
            try:
                data, server = udp_socket.recvfrom(4096)
                split_nonce = data[:16]
                encrypt_data = data[16:]

                decrypt_data = aes_ctr_decrypt(
                    bytes.fromhex(key),
                    split_nonce,
                    encrypt_data
                )
                spk.write(decoder.decode(decrypt_data, frame_num))
            except socket.timeout:
                continue
    except Exception as e:
        logging.error(f"音频接收错误: {str(e)}")
    finally:
        spk.stop_stream()
        spk.close()

def on_mqtt_message(client, userdata, msg):
    global aes_opus_info, udp_socket, tts_state, recv_audio_thread, send_audio_thread
    try:
        message = json.loads(msg.payload)
        GUI_UPDATE_QUEUE.put((message.get('text', ''), "system"))
        logging.info(f"接收到 MQTT 消息: {message}")

        if message['type'] == 'hello':
            handle_hello_message(message)
        elif message['type'] == 'tts':
            tts_state = message['state']
        elif message['type'] == 'goodbye':
            handle_goodbye_message(message)
    except Exception as e:
        GUI_UPDATE_QUEUE.put((f"消息处理错误: {str(e)}", "error"))
        logging.error(f"消息处理错误: {str(e)}")

def handle_hello_message(message):
    global aes_opus_info, udp_socket, recv_audio_thread, send_audio_thread
    # 保持原有的 session_id
    if not aes_opus_info['session_id']:
        aes_opus_info['session_id'] = message.get('session_id', None)

    # 只更新必要的字段，防止覆盖其他信息
    aes_opus_info['udp'] = message.get('udp', aes_opus_info['udp'])
    logging.info(f"处理 HELO 消息完成，session_id: {aes_opus_info['session_id']}")

    # 重新连接 UDP 套接字和音频线程
    restart_audio_streams()

def restart_audio_streams():
    global aes_opus_info, recv_audio_thread, send_audio_thread, udp_socket

    # 关闭已有的连接和线程
    if udp_socket:
        udp_socket.close()
    if recv_audio_thread and recv_audio_thread.is_alive():
        recv_audio_thread.join()
    if send_audio_thread and send_audio_thread.is_alive():
        send_audio_thread.join()

    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.settimeout(1)
        udp_socket.connect((aes_opus_info['udp']['server'], aes_opus_info['udp']['port']))

        # 启动新的音频线程
        recv_audio_thread = threading.Thread(target=recv_audio, daemon=True)
        recv_audio_thread.start()
        send_audio_thread = threading.Thread(target=send_audio, daemon=True)
        send_audio_thread.start()
    except Exception as e:
        logging.error(f"UDP连接失败: {str(e)}")

def handle_goodbye_message(message):
    global aes_opus_info, udp_socket
    if message.get('session_id') == aes_opus_info['session_id']:
        aes_opus_info['session_id'] = None
        if udp_socket:
            udp_socket.close()
        GUI_UPDATE_QUEUE.put(("会话已结束", "system"))
        logging.info("会话已结束")

def send_heartbeat():
    global last_heartbeat, running, last_listen_stop_time
    while running:
        if time.time() - last_heartbeat > HEARTBEAT_INTERVAL and mqtt_client.is_connected():
            try:
                mqtt_client.publish(mqtt_info['publish_topic'], json.dumps({"type": "heartbeat"}))
                last_heartbeat = time.time()
                logging.info("心跳已发送")
            except Exception as e:
                GUI_UPDATE_QUEUE.put((f"心跳发送失败: {str(e)}", "error"))
                logging.error(f"心跳发送失败: {str(e)}")

        # 检查会话是否超时
        if last_listen_stop_time is not None and time.time() - last_listen_stop_time > 5:
            logging.info("会话超时，关闭会话")
            handle_goodbye_message(goodbye_msg)  # 强制关闭会话
            last_listen_stop_time = None

        time.sleep(1)

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        GUI_UPDATE_QUEUE.put(("MQTT连接成功", "system"))
        client.subscribe(mqtt_info['subscribe_topic'])
        logging.info("MQTT连接成功")
    else:
        GUI_UPDATE_QUEUE.put((f"MQTT连接失败，错误码: {rc}", "error"))
        logging.error(f"MQTT连接失败，错误码: {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    GUI_UPDATE_QUEUE.put(("MQTT连接断开，尝试重连...", "error"))
    logging.warning("MQTT连接断开，正在尝试重连...")
    time.sleep(RECONNECT_INTERVAL)
    client.reconnect()

def setup_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=mqtt_info['client_id'])
    mqtt_client.username_pw_set(mqtt_info['username'], mqtt_info['password'])
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect
    mqtt_client.on_message = on_mqtt_message
    try:
        mqtt_client.connect(mqtt_info['endpoint'], 8883, 60)
        mqtt_client.loop_start()
        logging.info("MQTT连接已初始化")
    except Exception as e:
        GUI_UPDATE_QUEUE.put((f"MQTT 连接初始化失败: {str(e)}", "error"))
        logging.error(f"MQTT 连接初始化失败: {str(e)}")

def on_space_key_press(event):
    global key_state, listen_state, aes_opus_info
    key_state = "press"
    GUI_UPDATE_QUEUE.put(("倾听中...", "user"))
    logging.info("Space 键按下: 开始监听")

    # 确保会话在空间键按下的时候是处于激活状态的
    if not aes_opus_info['session_id']:
        send_hello_message()
    else:
        send_listen_message("start")

def on_space_key_release(event):
    global key_state, last_listen_stop_time
    key_state = "release"
    GUI_UPDATE_QUEUE.put(("", "user"))
    logging.info("Space 键释放: 结束监听")

    send_listen_message("stop")
    last_listen_stop_time = time.time()  # 记录停止时间，用于超时处理

def send_hello_message():
    hello_msg = {
        "type": "hello",
        "version": 3,
        "transport": "udp",
        "audio_params": {
            "format": "opus",
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration": 60
        }
    }
    try:
        mqtt_client.publish(mqtt_info['publish_topic'], json.dumps(hello_msg))
        logging.info("HELLO 消息已发送")
    except Exception as e:
        GUI_UPDATE_QUEUE.put((f"HELLO 消息发送失败: {str(e)}", "error"))
        logging.error(f"HELLO 消息发送失败: {str(e)}")

def send_listen_message(state):
    if aes_opus_info['session_id']:
        msg = {
            "session_id": aes_opus_info['session_id'],
            "type": "listen",
            "state": state,
            "mode": "manual"
        }
        try:
            mqtt_client.publish(mqtt_info['publish_topic'], json.dumps(msg))
            logging.info(f"LISTEN 消息已发送，状态: {state}")
        except Exception as e:
            GUI_UPDATE_QUEUE.put((f"LISTEN 消息发送失败: {str(e)}", "error"))
            logging.error(f"LISTEN 消息发送失败: {str(e)}")

def button_pressed_callback(channel):
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        on_space_key_press(None)
    else:
        on_space_key_release(None)

def run():
    global audio, running
    try:
        # 初始化音频系统
        audio = pyaudio.PyAudio()

        # 初始化GUI
        root = Tk()
        chat_window = ChatWindow(root)

        # 初始化日志
        logging.info("程序启动")

        # 获取初始配置
        get_ota_version()

        # 设置MQTT
        setup_mqtt()

        # 启动心跳线程
        threading.Thread(target=send_heartbeat, daemon=True).start()

        # GPIO事件监听
        GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=button_pressed_callback, bouncetime=50)

        # 启动主线程
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass

    except Exception as e:
        logging.error(f"运行时错误: {str(e)}")
    finally:
        # 清理资源
        logging.info("程序退出，清理资源...")
        GPIO.cleanup()
        if udp_socket:
            udp_socket.close()
        if audio:
            audio.terminate()
        if mqtt_client:
            mqtt_client.loop_stop(force=True)
        logging.info("资源清理完成")

if __name__ == "__main__":
    run()