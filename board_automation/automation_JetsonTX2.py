#!/usr/bin/python3

import os
import time
import re
import math
import serial

from . import tools
from . import board_automation
from . import uart_reader
from . import wrapper_pyftdi
from . import wrapper_uboot


import pyftdi # hack
import pyftdi.misc # hexdump()


#===============================================================================
#===============================================================================

class Board_Setup():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer
        self.uarts = []

        # MAC:
        #   bit 0: I/G, where 0 = Individual and 1 = Group
        #   bit 1: U/L, where 0 = Universal and 1 = Local
        #   bit 2-23: OUI, 48:b0:2d belongs to NVIDIA
        #   bit 24-47: OUI specific number
        #
        # Fun fact: MACs of these forms can be used for VM:
        #   x2:xx... (b'xxxx0010)
        #   x6:xx... (b'xxxx0110)
        #   xA:xx... (b'xxxx1010)
        #   xE:xx... (b'xxxx1110)
        #
        self.MAC = '48:b0:2d:56:01:ed'

        self.tftp_ip = '10.0.0.11'
        self.tftp_server_ip = '10.0.0.10'


        print('Board_Setup wrapper_pyftdi.list_devices()')
        wrapper_pyftdi.list_devices()
        print('Board_Setup pyftdi.ftdi.Ftdi.show_devices()')
        pyftdi.ftdi.Ftdi.show_devices()

        print('Board_Setup init')

        # GPIO for power switch control
        self.gpio = pyftdi.gpio.GpioMpsseController()
        self.gpio.configure(
            url = 'ftdi://ftdi:232h:1/1',
            frequency = 10e6
        )

        #self.gpio = wrapper_pyftdi.get_pyftdi_gpio(
        #                'ftdi://ftdi:232h:1/1',
        #                use_mpsse = True
        #

        # system log
        uart = uart_reader.TTY_USB.find_device(
                   #serial    = '0001',
                   usb_path  = '1-4.2.2.1',
               )
        self.uarts.append(uart)

        # data channel. But we see boot log output here also from lk running
        # in TrustZone.
        uart = uart_reader.TTY_USB.find_device(
                   #serial    = None,
                   usb_path  = '1-4.2.2.3',
               )
        self.uarts.append(uart)


    #---------------------------------------------------------------------------
    def start(self):

        # ACBUS[0] as out
        self.gpio.set_direction(pins=0x0100, direction=0x0100)
        self.gpio.write(0x0000)
        #while True:
        #    print('on')
        #    self.gpio.write(0x0100)
        #    time.sleep(1)
        #    print('off')
        #    self.gpio.write(0x0000)
        #    time.sleep(1)


    #---------------------------------------------------------------------------
    def stop(self):

        self.gpio.set_direction(pins=0x0000, direction=0x0000)

        for u in self.uarts :
            pass # nothing do do


    #---------------------------------------------------------------------------
    def cleanup(self):
        self.stop()


#===============================================================================
#===============================================================================

class BoardAutomation(object):

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner, board_setup):
        self.generic_runner = generic_runner
        self.board_setup = board_setup
        self.monitors = []

        self.monitors.append(
            uart_reader.UART_Reader(
                device  = self.get_uart_syslog().device,
                name    = 'UART0',
                printer = generic_runner.run_context.printer,
            )
        )

        # Since we see boot log output on this UART also from lk running in
        # TrustZone, we attach a monitor here. This will be removed one the
        # board has booted, so we can use this as data channel.
        self.monitors.append(
            uart_reader.UART_Reader(
                device  = self.get_uart_data().device,
                name    = 'UART1',
                printer = generic_runner.run_context.printer,
            )
        )


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
        self.print('power on')
        self.gpio.write(0x0100)


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('power off')
        self.gpio.write(0x0000)


    #---------------------------------------------------------------------------
    def reset(self, delay = 0.1):
        self.power_off()
        time.sleep(delay)
        self.power_on()


#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):

        self.generic_runner = generic_runner

        printer = generic_runner.run_context.printer

        # a Board_Setup() instance know everything about how a specific baord
        # is connected.
        self.board_setup = Board_Setup(printer)

        # Automation knows general board instrumentation, it needs a specific
        # Board_Setup() instance to run.
        self.board = BoardAutomation(self.board_setup.gpio, printer)

        self.data_uart_socket = None

    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        if self.board:
            self.board.power_off()

        if self.board_setup:
            # this will also stop the log_monitor
            self.board_setup.stop()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        if self.board_setup:
            self.board_setup.cleanup()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def get_serial_socket(self):
        if not self.data_uart_socket:
            # this can happen when the proxy is active
            raise Exception('ERROR: data uart not available')

        return self.data_uart_socket


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        # image we will load
        img = self.generic_runner.run_context.system_image
        img_size = os.path.getsize(img)

        self.board_setup.start()

        # ensure the board is off
        self.board.power_off()
        time.sleep(0.2)

        self.board.start_system_log()
        # Activate monitor for data uart to get additional boot logs
        monitor = self.board.get_uart_data_monitor()
        assert monitor # if there was no exception, this must exist
        monitor.start(
            log_file = self.generic_runner.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log,
        )

        # Get the log stream
        log = self.generic_runner.get_system_log_line_reader()
        assert log # if there was no exception, this must exist

        # Set up U-Boot automation. It may look a bit odd to write to a monitor,
        # but that is a hack to make things work for now. The monitor has an I/O
        # channel inside, but we need to refactor things to get access to that
        # I/O channel. It would be best if we created the I/O channel and then
        # give it to the monitor and who else needs it, like we do it with the
        # system log stream.
        monitor = self.board.get_system_log_monitor()
        assert monitor # if there was no exception, this must exist
        uboot = wrapper_uboot.UBootAutomation(log, monitor.serial.write)
        assert uboot # if there was no exception, this must exist

        #port = get_system_log_monitor().port
        #while True:
        #    print('on')
        #    #port.cts = 1
        #    port.rts = 1
        #    #port.dtr = 1
        #    time.sleep(1)
        #    print('off')
        #    #port.cts = 0
        #    port.rts = 0
        #    #port.dtr = 0
        #    time.sleep(1)

        #time.sleep(0.1)
        self.board.power_on()

        # https://www.thegoodpenguin.co.uk/blog/diving-into-the-nvidia-jetson-nano-boot-process/
        #
        #  BPMP ROM starts Core, waits for CBoot notification to start firmwars
        #  EL3/ATF -> EL2/CBoot -> EL2/U-Boot -> EL2/Kernel
        #
        ret = log.find_matches_in_lines([
            ( 'Welcome to MB2(TBoot-BPMP)', 10 ),
            ( 'I> MB2(TBoot-BPMP) done', 5 ),
            ( 'NOTICE:  BL31: ', 2),
            ( 'I> Welcome to Cboot', 2),
            ( 'I> Kernel EP: 0x80600000, DTB: 0x80000000', 4),
            ( 'U-Boot 2020.04', 1),
            ( 'SoC: tegra186', 1)
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
             'U-Boot 2020.04-g46e4604c78 (Jul 26 2021 - 12:10:58 -0700)', 2)

        uboot.cmd('bdinfo')
        #
        #   0x1'8000'0000 +---------------------------------+
        #                 | reserved                        |
        #   0x1'7720'0000 +---------------------------------+
        #                 | DRAM Bank #4, size 0x20'0000    |
        #   0x1'7700'0000 +---------------------------------+
        #                 | reserved                        |
        #   0x1'7680'0000 +---------------------------------+
        #                 | DRAM Bank #3, size 0x20'0000    |
        #   0x1'7660'0000 +---------------------------------+
        #                 | reserved                        |
        #   0x1'7600'0000 +---------------------------------+
        #                 | DRAM Bank #2, size 0x20'0000    |
        #   0x1'75e0'0000 +---------------------------------+
        #                 | reserved                        |
        #   0x1'7580'0000 +---------------------------------+
        #                 | DRAM Bank #1, size 0x85600000   |
        #                 |                                 |
        #                 |  relocaddr   = 0xfff33000       |
        #                 |  reloc off   = 0x7feb3000       |
        #                 |  irq_sp      = 0xff7f9040       |
        #                 |  sp start    = 0xff7f9040       |
        #                 |  fdt_blob    = 0xff7f9058       |
        #                 |                                 |
        #   0x0'f020'0000 +---------------------------------+
        #                 | reserved                        |
        #   0x0'f000'0000 +---------------------------------+
        #                 | DRAM Bank #0, size 0x70000000   |
        #   0x0'8000'0000 +---------------------------------+
        #

        # some U-Boot env:
        #   board=p3636-0001
        #   board_name=p3636-0001
        #   ethaddr=48:b0:2d:56:01:ed
        #   soc=tegra186
        #   vendor=nvidia
        # some env customization may exist already, so we may see this:
        #   ipaddr=10.0.0.11
        #   serverip=10.0.0.10

        # Check that our MAC is 48:b0:2d:56:01:ed
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
        assert img.startswith('/host/')
        tftp_img = img.replace('/host/', 'seos_tests/', 1)

        # There are 390 MiB available at 0xd7a0ba60 - 0xf0000000, so we put the
        # ELF Loader's ELF image at 0xe0000000. The elfloader's build process
        # calculates the code segment's base address specifically for the
        # payload, sto ensure it is after all payload. Usually, the kernel is
        # put at the begin of the memory (0x80000000), so e.g.
        #
        #             +---------------------------+
        #             | elfloader-image.elf       | 22367528 Byte
        #  0xe0000000 +---------------------------+
        #             | unused                    |
        #             +---------------------------+
        #             | ELF-Loader Code + Data    |
        #  0x81685000 +---------------------------+
        #             | unused?                   | 4096 KiB
        #  0x81685000 +---------------------------+
        #             | capdl-loader              | 20708 KiB
        #  0x8027c000 +---------------------------+
        #             | unused?                   | 192 KiB
        #  0x8024c000 +---------------------------+
        #             | kernel                    | 2352 KiB
        #  0x80000000 +---------------------------+
        #

        elf_load_addr = 0x80000000

        uboot.cmd_tftp(
            elf_load_addr,
            self.board_setup.tftp_server_ip,
            tftp_img,
            img_size,
            self.board_setup.tftp_ip)

        uboot.cmd_bootelf(elf_load_addr)
        time.sleep(0.1)
        log.flush()

        # There is a monitor on UART1, stop it to use the UART for data.
        self.print('stop monitor for UART1')
        monitor = self.board.get_uart_data_monitor()
        assert monitor # if there was no exception, this must exist
        monitor.stop_monitor()
        assert not monitor.is_monitor_running()

        uart = self.board.get_uart_data()
        assert uart # if there was no exception, this must exist

        if self.generic_runner.run_context.use_proxy:
            uart = self.board.get_uart_data()
            self.generic_runner.startProxy(
                connection = f'UART:{uart.device}',
                enable_tap = True,
            )
        else:
            self.data_uart_socket = uart_reader.SerialSocketWrapper(uart.device)


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
