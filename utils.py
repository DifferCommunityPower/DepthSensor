import os
import serial.tools.list_ports

def find_port(manufacturer:str = 'FTDI'):
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if manufacturer in port.manufacturer:
            return port.device
    return None



# Tank constants
TANK_TYPE = 1
TANK_CAPACITY = 100
TANK_STANDARD = 0    

UNIT_MAPPING = {
    0x0000: "MPa",
    0x0001: "kPa",
    0x0002: "Pa",
    0x0003: "bar",
    0x0004: "mbar",
    0x0005: "kg/cm²",
    0x0006: "psi",
    0x0007: "mH₂O",
    0x0008: "mmH₂O",
    0x0009: "°C",
    0x000A: "cmH₂O"
}

SAMPLE_INTERVAL = 30

def getVersion() -> str:
    filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),"version")
    with open(filename) as f:
        return f.read().replace('\n','')

# formatting
def format_litres(p, v):
    return str("%.3f" % v) + "m3"

def format_percent(p, v):
    return str("%.1f" % v) + "%"

def format_n(p, v):
    return str("%i" % v)        