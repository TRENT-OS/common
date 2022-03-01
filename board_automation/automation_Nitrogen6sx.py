#!/usr/bin/python3

import os
import time
import pathlib

from . import tools
from . import board_automation
from . import relay_control
from . import sd_wire
from . import uart_reader
from . import wrapper_pyftdi


#===============================================================================
#===============================================================================

class Board_Setup():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer
        self.uarts = []

        self.relay_config = relay_control.Relay_Config({
                                'POWER': relay_control.Relay_Dummy()
                            })

        self.sd_wire = sd_wire.SD_Wire(
                    serial     = '202005170006',
                    usb_path   = '1-1.1.3.1.2',
                    mountpoint = '/media')


        # UART0 is for syslog
        uart = uart_reader.TTY_USB.find_device(
                serial    = None,
                usb_path  = '1-1.1.3.2:1.0'
               )
        self.uarts.append(uart)

        # UART1 is for data
        uart = uart_reader.TTY_USB.find_device(
                serial    = None,
                usb_path  = '1-1.1.3.4:1.0'
               )
        self.uarts.append(uart)


    #---------------------------------------------------------------------------
    def cleanup(self):

        if self.log_monitor:
            self.log_monitor.stop()

        if self.sd_wire:
            self.sd_wire.switch_to_host()


#===============================================================================
#===============================================================================

class BoardAutomation(object):

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner, board_setup):

        self.monitors = []

        self.generic_runner = generic_runner
        self.printer = generic_runner.run_context.printer
        self.board_setup = board_setup

        uart_syslog = self.get_uart_syslog()
        assert uart_syslog
        monitor = uart_reader.UART_Reader(
                    device  = uart_syslog.device,
                    name    = 'UART0',
                    printer = generic_runner.run_context.printer)
        self.monitors.append(monitor)


        req_relays = ['POWER']
        relay_config = self.board_setup.relay_config
        if not relay_config.check_relays_exist(req_relays):
            raise Exception(f'relay configuration invalid, need {req_relays}')
        # put all relays in a well defined state
        relay_config.relay_config.set_all_off()


    #---------------------------------------------------------------------------
    def stop(self):
        self.power_off()
        self.stop_system_log()
        for monitor in self.monitors:
            monitor.stop()
        if self.board_setup:
            if self.board_setup.sd_wire:
                self.board_setup.sd_wire.switch_to_host()

    #---------------------------------------------------------------------------
    def cleanup(self):
        if self.board_setup:
            self.board_setup.cleanup()

    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)

    #---------------------------------------------------------------------------
    def get_uart_syslog(self):
        uarts = self.board_setup.uarts
        if (len(uarts) < 1):
            raise Exception('no uart with syslog')
        return uarts[0]

    #---------------------------------------------------------------------------
    def get_uart_data(self):
        uarts = self.board_setup.uarts
        if (len(uarts) < 2):
            raise Exception('no uart for data')
        return uarts[1]

    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('power on')
        self.board_setup.relay_config.POWER.set_on()

    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('power off')
        self.board_setup.relay_config.POWER.set_off()

    #---------------------------------------------------------------------------
    def boot(self):
        self.print('boot')
        self.power_on()


#===============================================================================
#===============================================================================

import serial

class UART_Socket():

    def __init__(self, uart):
        self.port = serial.Serial(uart.device, 115200, timeout=1)


    def send(self, data):
        self.port.write(data)


#===============================================================================
#===============================================================================


class BoardRunner(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):

        self.data_uart = None

        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer

        # Get setup for a specific board. The generic_runner.run_context is
        # supposed to contain something that we can use here to pick the right
        # board. For now, there is only one board.
        self.board_setup = BoardSetup(printer)

        # initilaize generic board automation with the specific board
        self.board = BoardAutomation(generic_runner, self.board_setup)

    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, nothing special here
    # def do_cleanup(self):


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        # make sure the board if powered off
        self.board.power_off()
        time.sleep(0.1)

        # setup the SD card
        mp = self.board_setup.sd_wire.switch_to_host_and_mount(timeout_sec = 5)

        self.print('content of {}'.format(mp))
        tools.print_files_from_folder(mp)

        self.board_setup.sd_wire.copy_file_to_card(
            self.run_context.system_image)

        self.board_setup.sd_wire.unmount_and_switch_to_device(timeout_sec = 5)

        # now the board is ready to boot, enable the UART logger and switch
        # the power on
        self.board_setup.log_monitor.start(
            log_file = self.system_log_file.name,
            print_log = print_log)
        time.sleep(0.1)

        self.board.boot()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        if self.board:
            self.board.stop()
        self.data_uart = None

    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.stop()
        if self.board:
            self.board.cleanup()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def get_serial_socket(self):
        if self.generic_runner.is_proxy_running():
            raise Exception('ERROR: Proxy uses data UART')

        if self.data_uart is None:
            uart = self.board_setup.get_uart_data()
            self.data_uart = SerialWrapper(uart.device, 115200, timeout=1)

        return self.data_uart


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
