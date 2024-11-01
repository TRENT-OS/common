#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import sys
import pathlib
import os
import traceback
import threading
import datetime
import time
import base64
import json
import requests

from . import tools

tools.add_subdir_to_sys_path(__file__, 'pyserial')
import serial


#===============================================================================
#===============================================================================

class TTY_USB():

    #---------------------------------------------------------------------------
    def __init__(self, device, vid, pid, serial, usb_path, driver):
        self.device   = device
        self.vid      = vid
        self.pid      = pid
        self.serial   = serial
        self.usb_path = usb_path
        self.driver   = driver


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def get_device_list(self_or_cls):

        dev_list = []

        base_folder = '/sys/class/tty'
        for dev in sorted(os.listdir(base_folder)):

            if not dev.startswith('ttyUSB'):
                continue

            dev_fqn = os.path.join(base_folder, dev)
            # each item in the folder is a symlink
            linked_dev = os.path.realpath(dev_fqn)
            # 1-4.2.2.1:1.0 -> 1-4.2.2.1
            usb_path = pathlib.Path(linked_dev).parts[-4].split(':',1)[0]

            usb_dev = os.path.join('/sys/bus/usb/devices', usb_path)

            def get_id_from_file(dn, id_file):
                id_file_fqn = os.path.join(dn, id_file)
                if not os.path.exists(id_file_fqn): return None
                with open(id_file_fqn) as f: return f.read().strip()

            vid = get_id_from_file(usb_dev, 'idVendor')
            pid = get_id_from_file(usb_dev, 'idProduct')
            serial = get_id_from_file(usb_dev, 'serial')

            # <item>/device/driver is also symlink
            driver = os.path.basename(
                        os.path.realpath(
                            os.path.join(dev_fqn, 'device/driver')))

            device = TTY_USB(
                        f'/dev/{dev}',
                        vid,
                        pid,
                        serial,
                        usb_path,
                        driver)

            dev_list.append(device)

        return dev_list


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def get_and_print_device_list(self_or_cls):

        print('USB/serial adapter list')
        dev_list = self_or_cls.get_device_list()
        for dev in dev_list:
            sn = f's/n {dev.serial}' if dev.serial else '[no s/n]'
            print(f'  {dev.device} is {dev.vid}:{dev.pid} {sn} at {dev.usb_path}, driver {dev.driver}')

        return dev_list


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def find_device(self_or_cls, serial = None, usb_path = None):

        dev_list = self_or_cls.get_and_print_device_list()
        print(dev_list)

        print(f'opening {usb_path}, {serial}')

        my_device = None

        if serial is not None:
            for dev in dev_list:
                print(f"serial comparison: {dev.serial} : {serial}")
                if (dev.serial == serial):
                    my_device = dev
                    break

        elif usb_path is not None:
            for dev in dev_list:
                print(f"serial comparison: {dev.usb_path} : {usb_path}")
                if (dev.usb_path == usb_path):
                    my_device = dev
                    break

        else:
            raise Exception('must specify device, serial and/or USB path')

        if not my_device:
            raise Exception('device not found')

        if usb_path and (usb_path != my_device.usb_path):
            raise Exception(f'USB path different, expected {usb_path}, got {my_device.usb_path}')

        if serial and (serial != my_device.serial):
            raise Exception(f'serial different, expected {serial}, got {my_device.serial}')

        sn = f's/n {dev.serial}' if dev.serial else '[no s/n]'
        usb_path = my_device.usb_path or '[None]'
        print(f'using {my_device.device} ({sn}, USB path {usb_path})')

        return my_device



#===============================================================================
#===============================================================================

class UART_Reader():

    #---------------------------------------------------------------------------
    def __init__(
            self,
            device,
            baud = 115200,
            printer = None):

        if not os.path.exists(device):
            raise Exception(f'UART missing: {device}')

        self.device  = device
        self.baud    = baud
        self.printer = printer

        self.port    = None
        self.monitor_thread = None
        self.stop_thread = False


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def monitor_channel_loop(self, f_log = None, print_log = False):

        start = datetime.datetime.now()

        while not self.stop_thread:

            assert self.port is not None
            assert self.port.is_open

            # This will throw a SerialException if the port is in use by another
            # process. We don't see any problem when opening the port, but here
            # when doing a read access.
            line = self.port.readline()
            if (len(line) == 0):
                # readline() encountered a timeout
                continue

            delta = datetime.datetime.now() - start

            # We support raw plain single byte ASCII chars only, because they
            # can always be decoded as all 256 bit combinations are valid. For
            # the standard string UTF-8 encoding with multi-byte chars, certain
            # bit pattern (e.g. from line garbage or transmission errors) would
            # raise decoding errors because they are not valid.
            # Remove any trailing '\r' or '\n'. Remove backspace chars, as we
            # don't want to have the cursor move backwards on the screen. Could
            # also print something like '<BACKSPACE>' instead
            line_str = line.decode('latin_1').rstrip('\r\n').replace('\b', '')

            if f_log is not None:
                f_log.write(f'[{delta}] {line_str}{os.linesep}')
                f_log.flush() # ensure things are really written

            if print_log:
                self.print(f'[{delta} {self.name}] {line_str}')


    #---------------------------------------------------------------------------
    def monitor_channel(self, log_file = None, print_log = False):

        try:
            if not log_file:
                self.monitor_channel_loop(None, print_log)

            else:
                with open(log_file, "w") as f_log:
                    self.monitor_channel_loop(f_log, print_log)

        except Exception as e:
            exc_info = sys.exc_info()
            self.print(f'Exception: {e}')
            traceback.print_exception(*exc_info)


    #---------------------------------------------------------------------------
    def start_monitor(self, log_file, print_log):
        assert self.port is not None
        assert self.monitor_thread is None
        self.monitor_thread = threading.Thread(
            target = self.monitor_channel,
            args = (log_file, print_log)
        )
        self.stop_thread = False
        self.monitor_thread.start()


    #---------------------------------------------------------------------------
    def stop_monitor(self):
        if self.monitor_thread is not None:
            self.stop_thread = True
            self.monitor_thread.join()
            self.monitor_thread = None


    #---------------------------------------------------------------------------
    def is_monitor_running(self):
        return self.monitor_thread is not None


    #---------------------------------------------------------------------------
    def start(self, log_file = None, print_log = False):

        # port must not be open
        assert self.port is None

        # When the port is not 'None', it is immediately opened on object
        # creation, no call to open() is necessary.
        # Using a timeout for reading prevents the monitoring thread from
        # blocking forever. Instead, it reads nothing, can check if the port is
        # still open and exit if not.
        self.port = serial.Serial(port     = self.device,
                                  baudrate = self.baud,
                                  bytesize = serial.serialutil.EIGHTBITS,
                                  parity   = serial.serialutil.PARITY_NONE,
                                  stopbits = serial.serialutil.STOPBITS_ONE,
                                  timeout  = 0.5,
                                  #xonxoff=False,
                                  #rtscts=False,
                                  #write_timeout=None,
                                  #dsrdtr=False,
                                  #inter_byte_timeout=None,
                                  #exclusive=None
                                  )
        if log_file or print_log:
            self.start_monitor(log_file, print_log)


    #---------------------------------------------------------------------------
    def stop(self):
        self.stop_monitor()

        if self.port is not None:
            self.port.close()
            self.port = None


#===============================================================================
#===============================================================================

"""
The UART_Proxy_Reader is part of the TRENTOS Harware CI.
It reads uart data via a webapi from a UART proxy.
"""
class UART_Proxy_Reader():

    #---------------------------------------------------------------------------
    def __init__(
            self,
            device,
            url,
            baud = 115200,
            name = 'UART',
            printer = None):

        

        self.device  = device
        self.baud    = baud
        self.printer = printer
        self.name    = name
        self.url     = url

        self.__check_device_api()

        self.port    = None
        self.monitor_thread = None
        self.stop_thread = False


    #---------------------------------------------------------------------------
    def __check_device_api(self):
        headers = {'accept': 'application/json'}
        full_url = f"{self.url}/{self.device}/info"
        response = requests.get(full_url, headers=headers)

        if not response.ok:
                raise Exception(f"Error {response.status_code}: {response.text}, device: {self.device}")

        self.print(json.dumps(response.json(), indent=4))


    #---------------------------------------------------------------------------
    def __control_uart_reading_api(self, control):
        headers = {'accept': 'application/json'}
        full_url = f"{self.url}/{self.device}/uart/{control}"
        response = requests.post(full_url, headers=headers)

        if not response.ok:
                raise Exception(f"Error {response.status_code}: {response.text}, device: {self.device}")
        
    
    #---------------------------------------------------------------------------
    def __start_uart_reading_api(self):
        self.__control_uart_reading_api("enable")


    #---------------------------------------------------------------------------
    def __stop_uart_reading_api(self):
        self.__control_uart_reading_api("disable")


    #---------------------------------------------------------------------------
    def __readline_api(self):
        headers = {'accept': 'application/text'}
        full_url = f"{self.url}/{self.device}/uart/readline"

        response = requests.get(full_url, headers=headers)

        if response.status_code in [404, 412]:
            raise Exception(f"Error {response.status_code}: Device {self.device}: {response.text}")

        if response.status_code == 202:
            time.sleep(1)
            return ""
        
        if response.ok:
            return base64.b64decode(response.text)
        raise Exception(f"Error {response.status_code}: Device {self.device}: {response.text}")


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def monitor_channel_loop(self, f_log = None, print_log = False):

        start = datetime.datetime.now()

        while not self.stop_thread:
            # This will throw a SerialException if the port is in use by another
            # process. We don't see any problem when opening the port, but here
            # when doing a read access.
            line = self.__readline_api()
            if not len(line):
                # No data received
                continue
            

            delta = datetime.datetime.now() - start

            # We support raw plain single byte ASCII chars only, because they
            # can always be decoded as all 256 bit combinations are valid. For
            # the standard string UTF-8 encoding with multi-byte chars, certain
            # bit pattern (e.g. from line garbage or transmission errors) would
            # raise decoding errors because they are not valid.
            # Remove any trailing '\r' or '\n'. Remove backspace chars, as we
            # don't want to have the cursor move backwards on the screen. Could
            # also print something like '<BACKSPACE>' instead
            line_str = line.decode('latin_1').rstrip('\r\n').replace('\b', '')

            if f_log is not None:
                f_log.write(f'[{delta}] {line_str}{os.linesep}')
                f_log.flush() # ensure things are really written

            if print_log:
                self.print(f'[{delta} {self.device}] {line_str}')


    #---------------------------------------------------------------------------
    def monitor_channel(self, log_file = None, print_log = False):

        try:
            if not log_file:
                self.monitor_channel_loop(None, print_log)

            else:
                with open(log_file, "w") as f_log:
                    self.monitor_channel_loop(f_log, print_log)

        except Exception as e:
            exc_info = sys.exc_info()
            self.print(f'Exception: {e}')
            traceback.print_exception(*exc_info)


    #---------------------------------------------------------------------------
    def start_monitor(self, log_file, print_log):
        assert self.monitor_thread is None
        self.monitor_thread = threading.Thread(
            target = self.monitor_channel,
            args = (log_file, print_log)
        )
        self.stop_thread = False
        self.monitor_thread.start()


    #---------------------------------------------------------------------------
    def stop_monitor(self):
        if self.monitor_thread is not None:
            self.stop_thread = True
            self.monitor_thread.join()
            self.monitor_thread = None


    #---------------------------------------------------------------------------
    def is_monitor_running(self):
        return self.monitor_thread is not None


    #---------------------------------------------------------------------------
    def start(self, log_file = None, print_log = False):
        self.__start_uart_reading_api()

        if log_file or print_log:
            self.start_monitor(log_file, print_log)

    #---------------------------------------------------------------------------
    def stop(self):
        self.stop_monitor()

        self.__stop_uart_reading_api()
