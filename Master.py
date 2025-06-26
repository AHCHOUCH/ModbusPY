#!/usr/bin/env python3
import time
import logging
import sys
import select
import termios
import tty
from pymodbus.client import ModbusTcpClient

# Configuration
HOST = '192.168.137.66'
PORT = 5020
SLAVE_ID = 1
POLL_INTERVAL = 2  # seconds

# Setup logging to file and console
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

file_handler = logging.FileHandler('client.log')
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger('TankMaster')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Control flags and overrides
auto_control = True
pump_override = None
valve_override = None
exit_flag = False
skip_next_poll = False

# Activation A logic
activation_a_active = False
activation_a_timer = 0

# Prepare terminal for non-blocking input
fd = sys.stdin.fileno()
old_settings = termios.tcgetattr(fd)
tty.setcbreak(fd)

def restore_terminal():
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# Connect to Modbus slave
client = ModbusTcpClient(HOST, port=PORT)
if not client.connect():
    logger.error(f"Cannot connect to {HOST}:{PORT}")
    restore_terminal()
    sys.exit(1)
logger.info('Connected to Tank Simulator')
print('Controls: [p]ump, [v]alve, [a]uto, [f]ill, [d]rain, [t]est, [q]uit')

try:
    while not exit_flag:
        # Display prompt
        sys.stdout.write('\r[p] [v] [a] [f] [d] [t] [q]> ')
        sys.stdout.flush()

        # Handle keyboard input
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1).lower()
            termios.tcflush(fd, termios.TCIFLUSH)
            if ch == 'q':
                exit_flag = True
                logger.info('Exit received')
            elif ch == 'a':
                auto_control = not auto_control
                pump_override = None if auto_control else pump_override
                logger.info(f"Auto control {'ON' if auto_control else 'OFF'}")
            elif ch == 'p':
                auto_control = False
                pump_override = not pump_override if pump_override is not None else True
                logger.info(f"Pump override {'ON' if pump_override else 'OFF'}")
            elif ch == 'v':
                valve_override = not valve_override if valve_override is not None else True
                logger.info(f"Valve override {'OPEN' if valve_override else 'CLOSED'}")
            elif ch == 'f':
                auto_control = False
                pump_override = True
                valve_override = False
                logger.info('Force FILL: Pump ON, Valve CLOSED')
            elif ch == 'd':
                auto_control = False
                pump_override = False
                valve_override = True
                logger.info('Force DRAIN: Pump OFF, Valve OPEN')
            elif ch == 't':
                logger.info('Sending Modbus packet with Transaction ID 0x0000 for Suricata PoC')
                raw_packet = b"\x00\x00\x00\x00\x00\x06\x01\x03\x00\x00\x00\x01"
                if client.socket:
                    try:
                        client.socket.send(raw_packet)
                        logger.info('Test packet sent.')

                        # Flush leftover response
                        client.socket.setblocking(0)
                        try:
                            while client.socket.recv(1024):
                                pass
                        except BlockingIOError:
                            pass
                        client.socket.setblocking(1)

                        skip_next_poll = True
                    except Exception as e:
                        logger.error(f'Failed to send test packet: {e}')
                else:
                    logger.error('No socket connection to send test packet.')

        if skip_next_poll:
            skip_next_poll = False
            time.sleep(POLL_INTERVAL)
            continue

        # Poll sensors
        rr = client.read_holding_registers(0, count=1, slave=SLAVE_ID)
        rc = client.read_coils(0, count=2, slave=SLAVE_ID)
        if not rr or not rc or rr.isError() or rc.isError():
            logger.error('Read error, exiting')
            break

        level = rr.registers[0]
        try:
            pump_state, valve_state = rc.bits[0], rc.bits[1]
        except IndexError:
            logger.error('Invalid coil response received, exiting')
            break

        # Check Activation A condition
        if not activation_a_active and 500 <= level <= 520:
            activation_a_active = True
            activation_a_timer = 5
            logger.info("Activation A: ACTIVATED")

        if activation_a_active:
            activation_a_timer -= 1
            if activation_a_timer <= 0:
                activation_a_active = False
                logger.info("Activation A: DEACTIVATED")

        # Decide pump action
        if pump_override is not None:
            target_pump = pump_override
        elif auto_control:
            if level < 300:
                target_pump = True
            elif level > 700:
                target_pump = False
            else:
                target_pump = pump_state
        else:
            target_pump = pump_state

        if target_pump != pump_state:
            client.write_coil(0, target_pump, slave=SLAVE_ID)
            logger.info(f"Pump set to {'ON' if target_pump else 'OFF'}")

        # Valve action
        if valve_override is not None and valve_override != valve_state:
            client.write_coil(1, valve_override, slave=SLAVE_ID)
            logger.info(f"Valve set to {'OPEN' if valve_override else 'CLOSED'}")

        # Log overall state
        logger.info(f"Level={level} Pump={'ON' if target_pump else 'OFF'} Valve={'OPEN' if valve_state else 'CLOSED'}")
        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    logger.info('Interrupted, exiting')
finally:
    client.close()
    restore_terminal()
    print()
    logger.info('Master shutdown')
