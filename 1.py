#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import time
import requests
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

# ============ GPIO配置 ==============
BUTTON_PIN = 17  # 使用GPIO17（物理引脚11）
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # 启用内部上拉电阻

# ============ 全局变量 ==============
OTA_VERSION_URL = 'https://api.tenclass.net/xiaozhi/ota/'
MAC_ADDR = 'xx:xx:xx:2d:b4:ba'  ## 自行修改这行

mqtt_info = {}
aes_opus_info = {"type": "hello", "version": 3, "transport": "udp",
                 "udp": {"server": "120.24.160.13", "port": 8884, "encryption": "aes-128-ctr",
                         "key": "263094c3aa28cb42f3965a1020cb21a7", "nonce": "01000000ccba9720b4bc268100000000"},
                 "audio_params": {"format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60},
                 "session_id": "b23ebfe9"}

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
iot_status_msg = {"session_id": "635aa42d", "type": "iot", "states": [
    {"name": "Speaker", "state": {"volume": 50}}, {"name": "Lamp", "state": {"power": False}}]}
goodbye_msg = {"session_id": "b23ebfe9", "type": "goodbye"}
local_sequence = 0
listen_state = None
tts_state = None
key_state = None
audio = None
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
conn_state = False
recv_audio_thread = threading.Thread()
send_audio_thread = threading.Thread()


# ============ 新增全局变量 ==============
GUI_UPDATE_QUEUE = queue.Queue()

# ============ GUI配置 ==============
class ChatWindow:
    def __init__(self, master):
        self.master = master
        master.title("聊天中")
        master.geometry("800x600")

        # 适配树莓派触摸屏
        master.attributes('-fullscreen', True)  # 全屏显示True
        master.bind("<Escape>", lambda e: master.attributes('-fullscreen', False))

        # 创建大字体
        self.custom_font = Font(family="WenQuanYi Zen Hei", size=48)  # 使用中文字体

        # 创建滚动区域
        frame = Frame(master)
        frame.pack(expand=True, fill="both")

        # 滚动文本框
        self.text_area = scrolledtext.ScrolledText(frame,
                                                 wrap="word",
                                                 font=self.custom_font,
                                                 state='disabled',
                                                 padx=20,
                                                 pady=20)
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
    post_data = {"flash_size": 16777216, "minimum_free_heap_size": 8318916, "mac_address": f"{MAC_ADDR}",
                 "chip_model_name": "esp32s3", "chip_info": {"model": 9, "cores": 2, "revision": 2, "features": 18},
                 "application": {"name": "xiaozhi", "version": "0.9.9", "compile_time": "Jan 22 2025T20:40:23Z",
                                 "idf_version": "v5.3.2-dirty",
                                 "elf_sha256": "22986216df095587c42f8aeb06b239781c68ad8df80321e260556da7fcf5f522"},
                 "partition_table": [{"label": "nvs", "type": 1, "subtype": 2, "address": 36864, "size": 16384},
                                     {"label": "otadata", "type": 1, "subtype": 0, "address": 53248, "size": 8192},
                                     {"label": "phy_init", "type": 1, "subtype": 1, "address": 61440, "size": 4096},
                                     {"label": "model", "type": 1, "subtype": 130, "address": 65536, "size": 983040},
                                     {"label": "storage", "type": 1, "subtype": 130, "address": 1048576,
                                      "size": 1048576},
                                     {"label": "factory", "type": 0, "subtype": 0, "address": 2097152, "size": 4194304},
                                     {"label": "ota_0", "type": 0, "subtype": 16, "address": 6291456, "size": 4194304},
                                     {"label": "ota_1", "type": 0, "subtype": 17, "address": 10485760,
                                      "size": 4194304}],
                 "ota": {"label": "factory"},
                 "board": {"type": "bread-compact-wifi", "ssid": "mzy", "rssi": -58, "channel": 6,
                           "ip": "192.168.124.38", "mac": "cc:ba:97:20:b4:bc"}}

    response = requests.post(OTA_VERSION_URL, headers=header, data=json.dumps(post_data))
    print('=========================')
    print(response.text)
    logging.info(f"get version: {response}")
    mqtt_info = response.json()['mqtt']


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
    global aes_opus_info, udp_socket, local_sequence, listen_state, audio
    key = aes_opus_info['udp']['key']
    nonce = aes_opus_info['udp']['nonce']
    server_ip = aes_opus_info['udp']['server']
    server_port = aes_opus_info['udp']['port']
    # 初始化Opus编码器
    encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)
    # 打开麦克风流, 帧大小，应该与Opus帧大小匹配
    mic = audio.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=960)
    try:
        while True:
            if listen_state == "stop":
                continue
                time.sleep(0.1)
            # 读取音频数据
            data = mic.read(960)
            # 编码音频数据
            encoded_data = encoder.encode(data, 960)
            # 打印音频数据
            # print(f"Encoded data: {len(encoded_data)}")
            # nonce插入data.size local_sequence_
            local_sequence += 1
            new_nonce = nonce[0:4] + format(len(encoded_data), '04x') + nonce[8:24] + format(local_sequence, '08x')
            # 加密数据，添加nonce
            encrypt_encoded_data = aes_ctr_encrypt(bytes.fromhex(key), bytes.fromhex(new_nonce), bytes(encoded_data))
            data = bytes.fromhex(new_nonce) + encrypt_encoded_data
            sent = udp_socket.sendto(data, (server_ip, server_port))
    except Exception as e:
        print(f"send audio err: {e}")
    finally:
        print("send audio exit()")
        local_sequence = 0
        udp_socket = None
        # 关闭流和PyAudio
        mic.stop_stream()
        mic.close()


def recv_audio():
    global aes_opus_info, udp_socket, audio
    key = aes_opus_info['udp']['key']
    nonce = aes_opus_info['udp']['nonce']
    sample_rate = aes_opus_info['audio_params']['sample_rate']
    frame_duration = aes_opus_info['audio_params']['frame_duration']
    frame_num = int(frame_duration / (1000 / sample_rate))
    print(f"recv audio: sample_rate -> {sample_rate}, frame_duration -> {frame_duration}, frame_num -> {frame_num}")
    # 初始化Opus编码器
    decoder = opuslib.Decoder(sample_rate, 1)
    spk = audio.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True, frames_per_buffer=frame_num)
    try:
        while True:
            data, server = udp_socket.recvfrom(4096)
            # print(f"Received from server {server}: {len(data)}")
            encrypt_encoded_data = data
            # 解密数据,分离nonce
            split_encrypt_encoded_data_nonce = encrypt_encoded_data[:16]
            # 十六进制格式打印nonce
            # print(f"split_encrypt_encoded_data_nonce: {split_encrypt_encoded_data_nonce.hex()}")
            split_encrypt_encoded_data = encrypt_encoded_data[16:]
            decrypt_data = aes_ctr_decrypt(bytes.fromhex(key),
                                           split_encrypt_encoded_data_nonce,
                                           split_encrypt_encoded_data)
            # 解码播放音频数据
            spk.write(decoder.decode(decrypt_data, frame_num))
    # except BlockingIOError:
    #     # 无数据时短暂休眠以减少CPU占用
    #     time.sleep(0.1)
    except Exception as e:
        print(f"recv audio err: {e}")
    finally:
        udp_socket = None
        spk.stop_stream()
        spk.close()


def recv_msg_from_mqtt_callbak(client, userdata, message):
    global aes_opus_info, udp_socket, tts_state, recv_audio_thread, send_audio_thread
    msg = json.loads(message.payload)
    # display_text = f"收到消息: {json.dumps(msg, ensure_ascii=False)}"
    display_text = f">>>: {msg.get('text', '')}"

    GUI_UPDATE_QUEUE.put((display_text, "system"))

    print(f"recv msg: {msg}")
    if msg['type'] == 'hello':
        aes_opus_info = msg
        udp_socket.connect((msg['udp']['server'], msg['udp']['port']))

        if not recv_audio_thread.is_alive():
            # 启动一个线程，用于接收音频数据
            recv_audio_thread = threading.Thread(target=recv_audio)
            recv_audio_thread.start()
        else:
            print("recv_audio_thread is alive")
        # 检查send_audio_thread线程是否启动
        if not send_audio_thread.is_alive():
            # 启动一个线程，用于发送音频数据
            send_audio_thread = threading.Thread(target=send_audio)
            send_audio_thread.start()
        else:
            print("send_audio_thread is alive")
    if msg['type'] == 'tts':
        tts_state = msg['state']
    if msg['type'] == 'goodbye' and udp_socket and msg['session_id'] == aes_opus_info['session_id']:
        print(f"recv good bye msg")
        aes_opus_info['session_id'] = None


def push_mqtt_msg(message):
    global mqtt_info
    publish.single(mqtt_info['publish_topic'], json.dumps(message), hostname=mqtt_info['endpoint'],
                   port=8883, client_id=mqtt_info['client_id'], auth={"username": mqtt_info['username'],
                                                                      "password": mqtt_info['password']}, tls={})


def test_aes():
    nonce = "0100000030894a57f148f4f900000000"
    key = "f3aed12668b8bc72ba41461d78e91be9"

    plaintext = b"Hello, World!"

    # Encrypt the plaintext
    ciphertext = aes_ctr_encrypt(bytes.fromhex(key), bytes.fromhex(nonce), plaintext)
    print(f"Ciphertext: {ciphertext.hex()}")

    # Decrypt the ciphertext back to plaintext
    decrypted_plaintext = aes_ctr_decrypt(bytes.fromhex(key), bytes.fromhex(nonce), ciphertext)
    print(f"Decrypted plaintext: {decrypted_plaintext}")


def test_audio():
    key = urandom(16)  # AES-256 key
    print(f"Key: {key.hex()}")
    nonce = urandom(16)  # Initialization vector (IV) or nonce for CTR mode
    print(f"Nonce: {nonce.hex()}")

    # 初始化Opus编码器
    encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)
    decoder = opuslib.Decoder(16000, 1)
    # 初始化PyAudio
    p = pyaudio.PyAudio()

    # 打开麦克风流, 帧大小，应该与Opus帧大小匹配
    mic = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=960)
    spk = p.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True, frames_per_buffer=960)

    try:
        while True:
            # 读取音频数据
            data = mic.read(960)
            # 编码音频数据
            encoded_data = encoder.encode(data, 960)
            # 加密数据，添加nonce
            encrypt_encoded_data = nonce + aes_ctr_encrypt(key, nonce, bytes(encoded_data))
            # 解密数据,分离nonce
            split_encrypt_encoded_data_nonce = encrypt_encoded_data[:len(nonce)]
            split_encrypt_encoded_data = encrypt_encoded_data[len(nonce):]
            decrypt_data = aes_ctr_decrypt(key, split_encrypt_encoded_data_nonce, split_encrypt_encoded_data)
            # 解码播放音频数据
            spk.write(decoder.decode(decrypt_data, 960))
            # print(f"Encoded frame size: {len(encoded_data)} bytes")
    except KeyboardInterrupt:
        print("停止录制.")
    finally:
        # 关闭流和PyAudio
        mic.stop_stream()
        mic.close()
        spk.stop_stream()
        spk.close()
        p.terminate()


def on_space_key_press(event):
    global key_state, udp_socket, aes_opus_info, listen_state, conn_state
    if key_state == "press":
        return
    key_state = "press"
    # 判断是否需要发送hello消息
    if conn_state is False or aes_opus_info['session_id'] is None:
        conn_state = True
        # 发送hello消息,建立udp连接
        hello_msg = {"type": "hello", "version": 3, "transport": "udp",
                     "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}
        push_mqtt_msg(hello_msg)
        print(f"send hello message: {hello_msg}")
    if tts_state == "start" or tts_state == "entence_start":
        # 在播放状态下发送abort消息
        push_mqtt_msg({"type": "abort"})
        print(f"send abort message")
    if aes_opus_info['session_id'] is not None:
        # 发送start listen消息
        msg = {"session_id": aes_opus_info['session_id'], "type": "listen", "state": "start", "mode": "manual"}
        print(f"send start listen message: {msg}")
        push_mqtt_msg(msg)


def on_space_key_release(event):
    global aes_opus_info, key_state
    key_state = "release"
    # 发送stop listen消息
    if aes_opus_info['session_id'] is not None:
        msg = {"session_id": aes_opus_info['session_id'], "type": "listen", "state": "stop"}
        print(f"send stop listen message: {msg}")
        push_mqtt_msg(msg)

def button_pressed_callback(channel):
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        GUI_UPDATE_QUEUE.put(("倾听", "user"))
        on_space_key_press(None)
    else:
        GUI_UPDATE_QUEUE.put(("。。。", "user"))
        on_space_key_release(None)

# ============ 主程序修改 ==============
def run():
    global mqtt_info

    # 必须在主线程初始化Tkinter
    root = Tk()
    chat_window = ChatWindow(root)

    # 启动GUI更新循环
    root.after(100, chat_window.check_queue)

    # 在独立线程运行网络相关操作
    network_thread = threading.Thread(target=network_task)
    network_thread.daemon = True
    network_thread.start()

    # 主线程运行GUI
    root.mainloop()

def network_task():
    get_ota_version()
    subscribe_topic = mqtt_info['subscribe_topic'].split("/")[0] + '/p2p/GID_test@@@' + MAC_ADDR.replace(':', '_')

    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH,
                        callback=button_pressed_callback,
                        bouncetime=50)

    try:
        subscribe.callback(recv_msg_from_mqtt_callbak, subscribe_topic,
                          hostname=mqtt_info['endpoint'], port=8883,
                          client_id=mqtt_info['client_id'],
                          auth={"username": mqtt_info['username'],
                               "password": mqtt_info['password']}, tls={})
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    audio = pyaudio.PyAudio()
    try:
        run()
    except KeyboardInterrupt:
        udp_socket.close()
        audio.terminate()


