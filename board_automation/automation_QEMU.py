#!/usr/bin/python3

import sys
import socket
import time
import os
import subprocess
import threading

from . import tools
from . import process_tools
from . import board_automation


#===============================================================================
#===============================================================================

class QemuProxyRunner(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, proxy_cfg_str = None):

        super().__init__(run_context, None)

        self.proxy_cfg_str = proxy_cfg_str

        self.process_qemu = None
        self.process_proxy = None

        self.serial_socket = None


    #---------------------------------------------------------------------------
    def is_qemu_running(self):
        return self.process_qemu and self.process_qemu.is_running()


    #---------------------------------------------------------------------------
    def is_proxy_running(self):
        return self.process_proxy and self.process_proxy.is_running()


    #---------------------------------------------------------------------------
    def start_qemu(self, cmd_arr, print_log):

        assert( not self.is_qemu_running() )

        self.process_qemu = process_tools.ProcessWrapper(
                                cmd_arr,
                                log_file_stdout = self.get_log_file_fqn('qemu_out.txt'),
                                log_file_stderr = self.get_log_file_fqn('qemu_err.txt'),
                                printer = self.run_context.printer,
                                name = 'QEMU'
                            )

        self.print('starting QEMU: {}'.format(' '.join(cmd_arr)))
        self.print('  QEMU stdout:   {}'.format(self.process_qemu.log_file_stdout))
        self.print('  QEMU stderr:   {}'.format(self.process_qemu.log_file_stderr))

        self.process_qemu.start(print_log)

        # start the monitor for the system log after the QEMU process has been
        # started. We can't start it before, because in this case it will
        # terminate immediately as there is neither a process nor a file.
        if print_log:
            self.system_log_file.start_monitor(
                printer = self.run_context.printer,
                checker_func = lambda: self.is_qemu_running()
            )


    #---------------------------------------------------------------------------
    def start_proxy(self, cmd_arr, print_log):

        assert( not self.is_proxy_running() )

        self.process_proxy = process_tools.ProcessWrapper(
                                cmd_arr,
                                log_file_stdout = self.get_log_file_fqn('proxy_out.txt'),
                                log_file_stderr = self.get_log_file_fqn('proxy_err.txt'),
                                printer = self.run_context.printer,
                                name = 'Proxy'
                            )

        self.print('starting Proxy: {}'.format(' '.join(cmd_arr)))
        self.print('  proxy stdout:   {}'.format(self.process_proxy.log_file_stdout))
        self.print('  proxy stderr:   {}'.format(self.process_proxy.log_file_stderr))

        self.process_proxy.start(print_log)


    #---------------------------------------------------------------------------
    def get_qemu_serial_connection_params(self, serial_qemu_connection):

        if(serial_qemu_connection == 'PTY'):

            # must use '-S' to freeze the QEMU at startup, unfreezing happens
            # when the other end of PTY is connected
            return ['-S', '-serial', 'pty']

        elif (serial_qemu_connection == 'TCP'):

            # QEMU will freeze on startup until it can connect to the server
            return ['-serial', 'tcp:localhost:4444,server']

        else:

            return ['-serial', '/dev/null']


    #---------------------------------------------------------------------------
    def get_qemu_machine_params(self):

        qemu_mapping = {
            # <plat>: ['<qemu-binary-arch>', '<qemu-machine>'],
            'imx6':      ['arm',     'sabrelite'],
            'migv':      ['riscv64', 'virt'],
            'rpi3':      ['aarch64', 'raspi3'],
            'spike':     ['riscv64', 'spike_v1.10'],
            'zynq7000':  ['arm',     'xilinx-zynq-a9'],
        }.get(self.run_context.platform, None)
        assert(qemu_mapping is not None)

        return [ 'qemu-system-{}'.format(qemu_mapping[0]),
                 '-machine', qemu_mapping[1],
                 '-m', 'size=1024M',
                 '-nographic']


    #---------------------------------------------------------------------------
    def connect_qemu_serial_to_tcp_socket(self):

        # socket must not be connected
        assert(self.serial_socket is None)

        self.print('connecting QEMU serial port to TCP socket')
        self.serial_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serial_socket.connect( ('127.0.0.1', 4444) )


    #---------------------------------------------------------------------------
    def connect_qemu_serial_to_proxy(self, proxy_app, serial_qemu_connection, print_log):

        # QEMU must be running
        assert( self.is_qemu_running() )

        assert(proxy_app is not None )
        if not os.path.isfile(proxy_app):
            raise Exception('ERROR: missing proxy app: {}'.format(proxy_app))

        connection_mode = None

        if (serial_qemu_connection == 'PTY'):

            # search for dev/ptsX info in QEMU's output, it used to be printed
            # to  stderr but QEMU 4.2 changed it to stdout
            pattern = re.compile('(\/dev\/pts\/\d)')
            match = None
            for filename in [
                self.process_qemu.log_file_stdout,
                self.process_qemu.log_file_stderr
            ]:
                match = Log_File(filename).find_match_in_lines(
                            pattern,
                            tools.Timeout_Checker(5))
                if match is not None:
                    break;

            if match is None:
                raise Exception('ERROR: could not get QEMU''s /dev/ptsX')

            connection_mode = 'PTY:{}'.format(match) # PTY to connect to

        elif (serial_qemu_connection == 'TCP'):
            connection_mode = 'TCP:4444'

        else:
            raise Exception(
                'ERROR: invalid Proxy/QEMU_connection: {}'.format(
                    serial_qemu_connection))

        # start the proxy
        assert( connection_mode is not None )
        cmd_proxy = [
            proxy_app,
            '-c', connection_mode,
            '-t', '1' # enable TAP
        ]

        self.start_proxy(cmd_proxy, print_log)

        if (serial_qemu_connection == 'PTY'):
            # QEMU starts up in halted mode, must send the 'c' command to
            # let it boot the system
            self.print('releasing QEMU from halt mode')
            qemu_in = self.process_qemu.process.stdin
            qemu_in.write(b'c\n')
            qemu_in.flush()


    #----------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_start(self, print_log):

        serial_qemu_connection = 'TCP'

        proxy_app = None

        if self.proxy_cfg_str:
            arr = self.proxy_cfg_str.split(',')
            proxy_app = arr[0]
            if (1 != len(arr)):
                serial_qemu_connection = arr[1]

        qemu_cmd = self.get_qemu_machine_params() + \
                   self.get_qemu_serial_connection_params(
                        serial_qemu_connection) + \
                   [
                       '-serial', 'file:{}'.format(self.system_log_file.name),
                       '-kernel', self.run_context.system_image,
                   ]

        self.start_qemu(qemu_cmd, print_log)

        # give QEMU process time to start. Instead of using a fixed value here
        # that was found by testing, we should use smarter methods an retries
        # with timeouts to determine if QEMU is working as expected.
        time.sleep(0.2)

        # either start proxy and connect it to QEMU's serial port or give the
        # tests access to the serial port for it's own usage.
        if proxy_app:
            self.connect_qemu_serial_to_proxy(
                proxy_app,
                serial_qemu_connection,
                print_log)
        else:
            self.connect_qemu_serial_to_tcp_socket()

        #self.print('QEMU up and system running')

        # QEMU is starting up now. If some output is redirected to files, they
        # may not exist until there is some actual output. There is not much
        # gain if we sleep here hoping the file pop into existence. The caller
        # should take care of this an deal with cases where the file does not
        # exists yet.


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner: nothing special here
    # def do_stop(self):


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_cleanup(self):
        if self.is_proxy_running():
            #self.print('terminating Proxy...')
            self.process_proxy.terminate()
            self.process_proxy = None

        if self.serial_socket:
            self.serial_socket.close()
            self.serial_socket = None

        if self.is_qemu_running():
            #self.print('terminating QEMU...')
            self.process_qemu.terminate()
            self.process_qemu = None


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def get_serial_socket(self):
        return self.serial_socket
