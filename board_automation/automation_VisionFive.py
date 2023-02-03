#!/usr/bin/python3

import os
import time

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

        self.MAC = '???'

        self.tftp_ip = '10.0.0.31'
        self.tftp_server_ip = '10.0.0.10'

        # UART0 is for syslog
        uart = uart_reader.TTY_USB.find_device(
                        # 10c4:ea60 s/n 0001 at 1-4.2.1.4.1.4, driver cp210x
                        # 1a86:7523 [no s/n] at 1-4.2.1.4.1, driver ch341-uart
                        #serial    = '...',
                        usb_path  = '1-4.2.1.3.3'                     )
        self.uarts.append(uart)

        # ToDo: GPIO setup
        #
        #       use RasPi Pico as USB-UART -> GPIO Adapter based on
        #       https://github.com/Noltari/pico-uart-bridge
        self.gpio = pyftdi.gpio.GpioMpsseController()
        self.gpio.configure(
            url = 'ftdi://ftdi:232h:1/1',
            frequency = 10e6
        )

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
    def cleanup(self):
        if self.gpio:
            self.gpio.set_direction(pins=0x0000, direction=0x0000)
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

        uart_syslog = self.get_uart_syslog()
        assert uart_syslog
        monitor = uart_reader.UART_Reader(
                    device  = uart_syslog.device,
                    name    = 'UART0',
                    printer = generic_runner.run_context.printer)
        self.monitors.append(monitor)


    #---------------------------------------------------------------------------
    def stop(self):
        self.power_off()
        self.stop_system_log()
        for monitor in self.monitors:
            monitor.stop()
        if self.board_setup.sd_wire:
            self.board_setup.sd_wire.switch_to_host()


    #---------------------------------------------------------------------------
    def cleanup(self):
        self.board_setup.cleanup()


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)

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
    def get_system_log_monitor(self):
        if (len(self.monitors) < 1):
            raise Exception('no syslog monitor')
        return self.monitors[0]


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
    def get_uboot_automation(self, log = None):
        if log is None:
            log = self.generic_runner.get_system_log_line_reader()
        monitor = self.get_system_log_monitor()
        assert monitor
        # It may look a bit odd to write to a monitor, but that is a hack to
        # make things work for now. The monitor has an I/O channel inside, but
        # we need to refactor things to get access to that I/O channel. It would
        # be best if we created the I/O channel and then give it to the monitor
        # and who else needs it, like we do it with the system log stream.
        return wrapper_uboot.UBootAutomation(log, monitor.port.write)


    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('no automation, power on manually')
        self.board_setup.gpio.write(0x0100)


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('no automation, power off manually')
        self.board_setup.gpio.write(0x0000)


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
        self.data_uart = None

        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer

        # Get setup for a specific board. The generic_runner.run_context is
        # supposed to contains something that we can use here to pick the right
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
        log = self.generic_runner.get_system_log_line_reader()
        uboot = self.board.get_uboot_automation(log)
        self.board.power_on()

        ret = log.find_matches_in_lines([
            ( [ 'bootloader version:211102-0b86f96' ], 10 ),
            # There is a test running that takes it's time
            ( [ 'crc check PASSED' ], 15 ),
            ( [ 'bootloader.' ], 1),
            ( [ 'OpenSBI v1.0' ], 1),
            ( [ 'Platform Name             : StarFive VisionFive V1' ], 1),
            ( [ 'U-Boot 2022.04-rc2-VisionFive (Mar 07 2022 - 21:12:22 +0800)StarFive' ], 5),
            ( [ 'Model: StarFive VisionFive V1' ], 1),
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
             'U-Boot 2022.04-rc2-VisionFive (Mar 07 2022 - 21:12:22 +0800)StarFive', 2)

        # some output from "printenv" or "env print":
        #
        #   ... ??? ...

        # Check that our MAC matches
        uboot.check_env('ethaddr', self.board_setup.MAC)

#        # Give the board an IP address for TFTP boot.
#        uboot.set_board_ip_addr(self.board_setup.tftp_ip)
#
#        # This is still a hack, where we have a TFTP server running on the host
#        # and it has a folder 'seos_tests' that points to the same holder on the
#        # host, that is mounted into the docker container at 'host'.
#        # Ideally, we would run our own TFTP server
#        #    https://github.com/mpetazzoni/ptftpd
#        #    https://github.com/sirMackk/py3tftp
#        #
        img = self.generic_runner.run_context.system_image
        img_size = os.path.getsize(img)
#        assert img.startswith('/host/')
#        tftp_img = img.replace('/host/', 'seos_tests/', 1)
#
#        # ToDo: explain why we use this load address
#        elf_load_addr = 0x40000000
#
#        uboot.cmd_tftp(
#            elf_load_addr,
#            self.board_setup.tftp_server_ip,
#            tftp_img,
#            img_size,
#            self.board_setup.tftp_ip)
#
#        uboot.cmd_bootelf(elf_load_addr)
#        time.sleep(0.1)
#        log.flush()


        self.write_uart0(b'loads 0x8590a800\n')
        time.sleep(0.1)
        log.set_timeout(0)
        log.flush()

        #import pathlib
        #img_srec = pathlib.Path(img).with_suffix('.srec')
        (basename, _) = os.path.splitext(img)
        img_srec = f'{basename}.srec'
        if not os.path.exists(img_srec):
            raise Exception(f'missing {img_srec}')

        print(f'loading {img_srec}')
        with open(img_srec, 'rb') as f:
            # file_content = f.read()
            for idx, line in enumerate(f):
                self.write_uart0(line)
                if (0 == idx % 2048): print(idx)
        print('srec done')

        time.sleep(10)
        log.set_timeout(0)
        log.flush()

        # manually upload via ymodem

        # run: picocom --send-cmd="sb -vv" --receive-cmd="rb -vvv" ...
        # in U-Boot use: loady <address>
        # Once it says "## Ready for binary (ymodem) ....." type C-a C-s and
        # choose the file.


        # There is a monitor on UART1, stop it to use the UART for data.
        # self.print('stop monitor for UART1')
        # uart1_monitor = self.board.monitors[1]
        # uart1_monitor.stop_monitor()
        # assert not uart1_monitor.is_monitor_running()
        # self.data_uart = SerialWrapper(uart1_monitor.port)
        # self.print('plat start done')


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.board.stop()
        self.data_uart = None


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.stop()
        self.board.cleanup()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner: ToDo: implement UART
    def get_serial_socket(self):
        if self.generic_runner.is_proxy_running():
            raise Exception('ERROR: Proxy uses data UART')

        if self.data_uart is None:
            uart = self.board_setup.get_data_uart()
            self.data_uart = SerialWrapper(uart.device, 115200, timeout=1)

        return self.data_uart


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
