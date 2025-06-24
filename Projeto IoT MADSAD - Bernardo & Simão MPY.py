
# ===== SCRIPT ATUALIZADO COM ESTATÍSTICAS E MENSAGENS OLED NO THINGSBOARD =====
import time
import random
import network
import ntptime
import json
import usocket as socket

from machine import Pin, SoftI2C, PWM, RTC
from mfrc522 import MFRC522
from ssd1306 import SSD1306_I2C
from servo import Servo
from apds9960LITE import APDS9960LITE
from umqtt.simple import MQTTClient

# ========== CONFIGURAÇÕES ==========
TOTAL_LUGARES = 5
PRECO_POR_MINUTO = 0.5
THINGSBOARD_HOST = "eu.thingsboard.cloud"
ACCESS_TOKEN = "EKBknhKTtyw2CyTZxv9A"
WIFI_SSID = "simaodias"
WIFI_PASSWORD = "12345678"
cartoes_autorizados = [
    [183, 214, 5, 1, 101]
]

# ========== CONECTAR AO WIFI ==========
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)
while not wlan.isconnected():
    time.sleep(1)
print("Conectado ao Wi-Fi")

# ========== HORA VIA NTP ==========
ntptime.host = "pool.ntp.org"
try:
    ntptime.settime()
except:
    print("Falha ao sincronizar hora NTP")
rtc = RTC()

def hora_atual_str():
    tm = time.localtime(time.time() + 3600)  # UTC+1
    return "{:02}:{:02}:{:02}".format(tm[3], tm[4], tm[5])

def segundos_entre(dt1, dt2):
    t1 = dt1[3]*3600 + dt1[4]*60 + dt1[5]
    t2 = dt2[3]*3600 + dt2[4]*60 + dt2[5]
    return max(t2 - t1, 1)

# ========== MQTT ==========
client = MQTTClient("client_id", THINGSBOARD_HOST, user=ACCESS_TOKEN, password="")
client.connect()
print("Conectado ao ThingsBoard via MQTT")

# ========== INICIALIZAÇÃO ==========
i2c = SoftI2C(scl=Pin(6), sda=Pin(5))
oled = SSD1306_I2C(128, 64, i2c)
apds9960 = APDS9960LITE(i2c)
apds9960.prox.enableSensor()
rdr = MFRC522(sck=7, mosi=9, miso=8, rst=3, cs=1)
servo = Servo(pin_id=2)
buzzer = PWM(Pin(4, Pin.OUT))

entradas = 0
saidas = 0
portao_aberto = False
tempo_ultimo_acesso = 0
tempo_aberto_ms = 5000
historico = []
entradas_ativas = {}
uid_contadores = {}

# ========== FUNÇÕES ==========
def beep(duration=200, freq=1000):
    buzzer.freq(freq)
    buzzer.duty(512)
    time.sleep_ms(duration)
    buzzer.duty(0)

def beep_acesso_negado():
    for _ in range(3):
        beep(100, 3000)
        time.sleep_ms(100)

def beep_sem_lugar():
    beep(500, 2500)
    time.sleep_ms(200)
    beep(150, 2000)
    time.sleep_ms(100)
    beep(150, 2000)

def beep_thank_you():
    beep(100, 1500)
    time.sleep_ms(100)
    beep(150, 1000)

def mostrar_oled(linhas):
    oled.fill(0)
    for i, linha in enumerate(linhas):
        oled.text(linha, 0, i * 10)
    oled.show()
    try:
        client.publish("v1/devices/me/attributes", json.dumps({"mensagem_oled": " | ".join(linhas)}))
    except Exception as e:
        print("Erro ao enviar mensagem OLED para ThingsBoard:", e)

def abrir_portao():
    global portao_aberto, tempo_ultimo_acesso
    servo.write(90)
    portao_aberto = True
    tempo_ultimo_acesso = time.ticks_ms()

def fechar_portao():
    global portao_aberto
    servo.write(0)
    portao_aberto = False

def lugares_ocupados():
    return entradas - saidas

def lugares_livres():
    return TOTAL_LUGARES - lugares_ocupados()

def enviar_json(dados):
    try:
        client.publish("v1/devices/me/telemetry", json.dumps(dados))
    except Exception as e:
        print("Erro ao enviar MQTT:", e)

# === Funções de Estatísticas ===
def calcular_lucro():
    return sum(reg.get("custo", 0) for reg in historico if reg.get("custo") is not None)

def total_entradas():
    return sum(1 for reg in historico if reg.get("tipo") == "entrada")

def total_negados():
    return sum(1 for reg in historico if reg.get("tipo") == "negado")

def total_sem_lugares():
    return sum(1 for reg in historico if reg.get("tipo") == "cheio")

# ========== LOOP PRINCIPAL ==========
servo.write(0)
mostrar_oled([f"Lugares: {lugares_livres()}"])

while True:
    if apds9960.prox.proximityLevel > 180 and not portao_aberto and lugares_ocupados() > 0:
        uids_disponiveis = [uid for uid, ids in entradas_ativas.items() if ids]
        if uids_disponiveis:
            uid = random.choice(uids_disponiveis)
            id_lista = entradas_ativas[uid]
            entrada_id = random.choice(id_lista)
            id_lista.remove(entrada_id)
            saidas += 1
            dt_saida = time.localtime(time.time() + 3600)
            for reg in historico:
                if "id" in reg and reg["id"] == entrada_id:
                    reg["tipo"] = "saida"
                    reg["hora_saida"] = hora_atual_str()
                    minutos = (segundos_entre(reg["dt_entrada"], dt_saida) + 59) // 60
                    reg["custo"] = minutos * PRECO_POR_MINUTO
                    mostrar_oled(["Boa Viagem", "Obrigado", f"Custo: {reg['custo']} EUR"])
                    beep_thank_you()
                    print("[SAÍDA]", reg)
                    enviar_json({
                        "tipo": "saida",
                        "id": reg["id"],
                        "uid": reg["uid"],
                        "hora_entrada": reg["hora_entrada"],
                        "hora_saida": reg["hora_saida"],
                        "custo": reg["custo"],
                        "permanencia_min": minutos,
                        "lugares_ocupados": lugares_ocupados(),
        "lugares_disponiveis": lugares_livres(),
                        "lucro_total": calcular_lucro(),
                        "total_entradas": total_entradas(),
                        "total_negados": total_negados(),
                        "total_sem_lugares": total_sem_lugares()
                    })
                    break
            abrir_portao()
            time.sleep(5)
            fechar_portao()
            mostrar_oled([f"Lugares: {lugares_livres()}"])
            time.sleep(2)

    (stat, tag_type) = rdr.request(rdr.REQIDL)
    if stat == rdr.OK:
        (stat, uid) = rdr.anticoll()
        if stat == rdr.OK:
            hora = hora_atual_str()
            if uid in cartoes_autorizados:
                if lugares_livres() > 0:
                    uid_t = tuple(uid)
                    uid_contadores[uid_t] = uid_contadores.get(uid_t, 0) + 1
                    entrada_id = f"{uid_t[-1]}-{uid_contadores[uid_t]}"
                    dt_entrada = time.localtime(time.time() + 3600)
                    reg = {
                        "tipo": "entrada",
                        "id": entrada_id,
                        "uid": uid,
                        "hora_entrada": hora,
                        "dt_entrada": dt_entrada
                    }
                    historico.append(reg)
                    entradas_ativas.setdefault(uid_t, []).append(entrada_id)
                    entradas += 1
                    mostrar_oled(["Acesso Autorizado"])
                    beep(100, 1500)
                    abrir_portao()
                    print("[ENTRADA]", reg)
                    enviar_json({
                        "tipo": "entrada",
                        "id": reg["id"],
                        "uid": reg["uid"],
                        "hora_entrada": reg["hora_entrada"],
                        "lugares_ocupados": lugares_ocupados(),
        "lugares_disponiveis": lugares_livres(),
                        "lucro_total": calcular_lucro(),
                        "total_entradas": total_entradas(),
                        "total_negados": total_negados(),
                        "total_sem_lugares": total_sem_lugares()
                    })
                    time.sleep(5)
                    fechar_portao()
                else:
                    mostrar_oled(["S/Lugares", "Disponiveis"])
                    beep_sem_lugar()
                    print(f"[CHEIO] UID: {uid} | Hora: {hora}")
                    historico.append({"tipo": "cheio", "uid": uid, "hora": hora})
                    enviar_json({
                        "tipo": "cheio",
                        "uid": uid,
                        "hora": hora,
                        "id": f"{uid[-1]}-X",
                        "total_sem_lugares": total_sem_lugares()
                    })
                    time.sleep(2)
            else:
                mostrar_oled(["ACESSO NEGADO", "CARREGUE O CARTAO"])
                beep_acesso_negado()
                print(f"[NEGADO] UID: {uid} | Hora: {hora}")
                historico.append({"tipo": "negado", "uid": uid, "tentativa_hora": hora})
                enviar_json({
                    "tipo": "negado",
                    "uid": uid,
                    "tentativa_hora": hora,
                    "total_negados": total_negados()
                })
                time.sleep(2)

    if portao_aberto and time.ticks_diff(time.ticks_ms(), tempo_ultimo_acesso) > tempo_aberto_ms:
        fechar_portao()

    if not portao_aberto:
        mostrar_oled([f"Lugares: {lugares_livres()}"])

    time.sleep(0.1)
