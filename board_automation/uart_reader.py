#!/usr/bin/python3

import sys
import pathlib
import os
import traceback
import threading
import datetime

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
                        '/dev/{}'.format(dev),
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
            print('  {} is {}:{} {} at {}, driver {})'.format(
                  dev.device,
                  dev.vid,
                  dev.pid,
                  's/n {}'.format(dev.serial) if dev.serial else '[no serial]',
                  dev.usb_path,
                  dev.driver))

        return dev_list


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def find_device(self_or_cls, serial = None, usb_path = None):

        dev_list = self_or_cls.get_and_print_device_list()

        print('opening {}, {}'.format(usb_path, serial))

        my_device = None

        if serial is not None:
            for dev in dev_list:
                if (dev.serial == serial):
                    my_device = dev
                    break;

        elif usb_path is not None:
            for dev in dev_list:
                if (dev.usb_path == usb_path):
                    my_device = dev
                    break;

        else:
            raise Exception('must specify device, serial and/or USB path')

        if not my_device:
            raise Exception('device not found')

        if usb_path and (usb_path != my_device.usb_path):
            raise Exception('USB path different, expected {}, got {}'.format(usb_path, my_device.usb_path))

        if serial and (serial != my_device.serial):
            raise Exception('serial different, expected {}, got {}'.format(serial, my_device.serial))

        print('using {} ({}, USB path {})'.format(
            my_device.device,
            my_device.serial or '[no s/n]',
            my_device.usb_path or ''))

        return my_device



#===============================================================================
#===============================================================================

class UART_Reader():

    #---------------------------------------------------------------------------
    def __init__(
            self,
            device,
            baud = 115200,
            name = 'UART',
            printer = None):

        if not os.path.exists(device):
            raise Exception('UART missing: {}'.format(device))

        self.device  = device
        self.baud    = baud
        self.printer = printer
        self.name    = name

        self.port    = None


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def monitor_channel_loop(self, f_log = None, print_log = False):

        start = datetime.datetime.now()

        while self.port and self.port.is_open:

            line = self.port.readline()
            if (len(line) == 0):
                # readline() encountered a timeout
                continue

            line_str = line.strip().decode('utf-8')

            # remove backspace chars, as we don't want to have the
            # cursor move backwards on the screen. Could also print
            # something like '<BACKSPACE>' instead
            line_str = line_str.replace('\b', '')

            delta = datetime.datetime.now() - start;

            msg = '[{}] {}{}'.format(delta, line_str, os.linesep)
            f_log.write(msg)
            f_log.flush() # ensure things are really written

            if print_log:
                msg = '[{} {}] {}'.format(delta, self.name, line_str)
                self.print(msg)


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
            self.print('Exception: {}'.format(e))
            traceback.print_exception(*exc_info)


    #---------------------------------------------------------------------------
    def start(self, log_file = None, print_log = False):

        # port must not be open
        assert(self.port is None)

        # use a timeout for reading, so the monitoring thread wont block
        # forever. Instead, it reads nothing, can check if the port is still
        # open and exit otherwise.
        self.port = serial.Serial(self.device, self.baud, timeout=1)

        threading.Thread(
            target = self.monitor_channel,
            args = (log_file, print_log)
        ).start()


    #---------------------------------------------------------------------------
    def stop(self):

        if self.port:
            port = self.port
            self.port = None
            port.close()
