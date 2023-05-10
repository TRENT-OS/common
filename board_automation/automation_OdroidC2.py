#!/usr/bin/python3

import os
import time
import pathlib

from . import relay_control
from . import sd_wire
from . import uart_reader
from . import wrapper_pyftdi
from . import wrapper_uboot


#===============================================================================
#===============================================================================

class BoardSetup():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer
        self.gpio = None
        self.sd_wire = None
        self.uarts = []

        self.MAC = '00:1e:06:37:8c:98'

        self.tftp_ip = '10.0.0.21'
        self.tftp_server_ip = '10.0.0.10'

        # self.gpio = wrapper_pyftdi.get_pyftdi_gpio('ftdi://ftdi:232h:1/1')
        # relay_board = relay_control.Relay_Board(self.gpio)
        #
        # self.relay_config = relay_control.Relay_Config({
        #                         'POWER':  relay_board.get_relay(0),
        #                         'notRUN': relay_board.get_relay(1),
        #                         'notPEN': relay_control.Relay_Dummy()
        #                      })
        #
        #
        # self.sd_wire = sd_wire.SD_Wire(
        #             serial     = 'sdw-7',
        #             usb_path   = '1-4.2.1.1.3',
        #             mountpoint = '/media')

        # UART0 is for syslog
        uart = uart_reader.TTY_USB.find_device(
                        #serial    = '...',
                        usb_path  = '1-4.2.1.1.2'
                     )
        self.uarts.append(uart)

        # UART1 is for data
        uart = uart_reader.TTY_USB.find_device(
                        #serial    = '...',
                        usb_path  = '1-4.2.1.1.3'
                     )
        self.uarts.append(uart)


    #---------------------------------------------------------------------------
    def cleanup(self):
        if self.gpio:
            self.gpio.close()
        for uart in self.uarts:
            pass # noting to do
        self.sd_wire = None


#===============================================================================
#===============================================================================

class BoardAutomation():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner, board_setup):
        self.generic_runner = generic_runner
        self.board_setup = board_setup
        self.monitors = []

        # create monitor for syslog
        self.monitors.append(
            uart_reader.UART_Reader(
                device  = self.get_uart_syslog().device,
                name    = 'UART0',
                printer = generic_runner.run_context.printer
            )
        )

        # test monitor for data UART
        self.monitors.append(
            uart_reader.UART_Reader(
                device  = self.get_uart_data().device,
                name    = 'UART1',
                printer = generic_runner.run_context.printer,
            )
        )


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
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)

    #---------------------------------------------------------------------------
    def get_uart_syslog(self):
        if not self.board_setup:
            raise Exception('missing board setup')
        uarts = self.board_setup.uarts
        if (len(uarts) < 1):
            raise Exception('no uart with syslog')
        return uarts[0]


    #---------------------------------------------------------------------------
    def get_uart_data(self):
        if not self.board_setup:
            raise Exception('missing board setup')
        uarts = self.board_setup.uarts
        if (len(uarts) < 2):
            raise Exception('no uart for data')
        return uarts[1]


    #---------------------------------------------------------------------------
    def get_system_log_monitor(self):
        if (len(self.monitors) < 1):
            raise Exception('no syslog monitor')
        return self.monitors[0]


    #---------------------------------------------------------------------------
    def get_uart_data_monitor(self):
        if (len(self.monitors) < 2):
            raise Exception('no syslog monitor')
        return self.monitors[1]


    #---------------------------------------------------------------------------
    def start_system_log(self):
        monitor = self.get_system_log_monitor()
        assert monitor
        monitor.start(
            log_file = self.generic_runner.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log)


    #---------------------------------------------------------------------------
    def stop_system_log(self):
        monitor = self.get_system_log_monitor()
        assert monitor
        monitor.stop()


    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('no automation, power on manually')


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('no automation, power off manually')


#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):

        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer

        # Initialized when first used.
        self.data_uart_socket = None

        # Get setup for a specific board. The generic_runner.run_context is
        # supposed to contain something that we can use here to pick the right
        # board. For now, there is only one board.
        self.board_setup = BoardSetup(printer)

        # initilaize generic board automation with the specific board
        self.board = BoardAutomation(generic_runner, self.board_setup)


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):
        # make sure the board is powered off and then turn it on
        self.board.power_off()
        time.sleep(0.1)

        if self.generic_runner.run_context.use_proxy:
            uart = self.board.get_data_uart()
            self.generic_runner.startProxy(
                connection = f'UART:{uart.device}',
                enable_tap = True,
            )

        self.board.start_system_log()

        # Activate monitor for data uart to get additional boot logs
        self.board.get_uart_data_monitor().start(
            log_file = self.generic_runner.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log,
        )

        log = self.generic_runner.get_system_log_line_reader()
        assert log # if there was no exception, this must exist

        # The UBoot wrapper needs a way to access the log and a function to send
        # commands. The syslog monitor has an UART's I/O channel inside, so this
        # is where we get the write function from. It's a bit hacky, we should
        # refactor things that we first obtain an I/O channel, and then give
        # this to the monitor and who else needs it.
        monitor = self.board.get_system_log_monitor()
        assert monitor # if there was no exception, this must exist
        uboot = wrapper_uboot.UBootAutomation(log, monitor.port.write)
        assert uboot # if there was no exception, this must exist

        self.board.power_on()

        ret = log.find_matches_in_lines([
            ( 'BL2 Built : 11:44:26, Nov 25 2015.', 10),
            ( 'Load fip header from SD, src: 0x0000c200, ', 1),
            ( 'Load bl30 from SD, src: 0x00010200, ', 1),
            ( 'Run bl30...', 1),
            ( 'Run bl301...', 1),
            ( 'U-Boot 2022.01-armbian (Feb 17 2023 - 22:33:25 +0000) odroid-c2', 2),
            ( 'Model: Hardkernel ODROID-C2', 1),
            ( 'eth0: ethernet@c9410000', 3),
        ])
        if not ret.ok:
            raise Exception(f'boot string #{len(ret.items)-1} not found: {ret.get_missing()}')

        # Let U-Boot run to the auto start interception prompt and then abort
        # to get us a shell.
        time.sleep(0.5)
        uboot.intercept_autostart()

        # Simple test if U-Boot interaction works. This also checks for a
        # specific version, as this happens to be what we have installed. So
        # any other version is unexpected for now and thus an error.
        uboot.cmd(
            'version',
             'U-Boot 2022.01-armbian (Feb 17 2023 - 22:33:25 +0000) odroid-c2', 2)

        # some output from "printenv" or "env print":
        #   arch=arm
        #   cpu=armv8
        #   soc=meson
        #   vendor=amlogic
        #   board=p200
        #   board_name=p200
        #   serial#=HKC213254E014018�
        #   ethaddr=00:1e:06:37:8c:98

        # Check that our MAC matches
        uboot.check_env('ethaddr', self.board_setup.MAC)

        # Give the board an IP address for TFTP boot.
        uboot.set_board_ip_addr(self.board_setup.tftp_ip)

        # This is still a hack, where we have a TFTP server running on the host
        # and it has a folder 'seos_tests' that points to the same holder on the
        # host, that is mounted into the docker container at 'host'.
        # Ideally, we would run our own TFTP server
        #    https://github.com/mpetazzoni/ptftpd
        #    https://github.com/sirMackk/py3tftp
        #
        img = self.generic_runner.run_context.system_image
        img_size = os.path.getsize(img)
        assert img.startswith('/host/')
        tftp_img = img.replace('/host/', 'seos_tests/', 1)

        # ToDo: explain why we use this load address
        #
        # 0x8000'0000 +-----------------------------------+ DRAM end
        #             | os_image.elf                      |
        # 0x4000'0000 +-----------------------------------+
        #             | boot.scr loaded by U-Boot         |
        # 0x0800'0000 +-----------------------------------+
        #             | (unused?)                         |
        # 0x0140'00b0 +-----------------------------------+
        #             | fip header                        |
        # 0x0140'0000 +-----------------------------------+
        #             | (unused?)                         |
        # 0x1011'1130 +-----------------------------------+
        #             | bl301                             |
        # 0x1010'0000 +-----------------------------------+
        #             | 1 MiByte scratch space, used for  |
        #             | SD card loading                   |
        #             |   bl30 (len 0x9ef0)               |
        #             |   bl301 (len 0x18c0)              |
        #             |   bl31/aka U-Boot (len 0x11130)   |
        #             |   bl33 (len 0xa21d0)              |
        # 0x0100'0000 +-----------------------------------+
        #             | 16 MiByte unused                  |
        # 0x0000'0000 +-----------------------------------+ DRAM start
        #

        elf_load_addr = 0x40000000

        uboot.cmd_tftp(
            elf_load_addr,
            self.board_setup.tftp_server_ip,
            tftp_img,
            img_size,
            self.board_setup.tftp_ip)

        uboot.cmd_bootelf(elf_load_addr)
        time.sleep(0.1)
        log.flush()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        if self.board:
            self.board.stop()
        self.data_uart_socket = None


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

        if self.data_uart_socket is None:
            uart = self.board.get_uart_data()
            assert uart # if there was no exception, this must exist
            self.data_uart_socket = uart_reader.SerialSocketWrapper(uart.device)

        return self.data_uart_socket


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
