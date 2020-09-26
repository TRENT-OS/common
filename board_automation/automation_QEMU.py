#!/usr/bin/python3

import sys
import traceback
import socket
import time
import os
import subprocess

from . import tools
from . import process_tools
from . import board_automation



#===============================================================================
#===============================================================================

class TcpBridge():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer

        self.thread_client = None
        self.socket_client = None

        self.thread_server = None
        self.server_socket = None
        self.server_socket_client = None

        # the buffer size value has has been picked based on observations, the
        # largest value seen so far was 4095, which might be related to
        # - the 4 KiByte pages that ARM and RISC-V uses
        # - seL4/CAmkES based systems often use shared buffers of 4 KiByte.
        self.buffer_size = 8192


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print('{}: {}'.format(__class__.__name__, msg))


    #---------------------------------------------------------------------------
    def close_server_sockets(self):
        s = self.server_socket_client
        self.server_socket_client = None
        if s:
            s.close()

        s = self.server_socket
        self.server_socket = None
        if s:
            s.close()


    #---------------------------------------------------------------------------
    def stop_server(self):

        if self.thread_server is None:
            return

        self.close_server_sockets()
        # since we have closed server_socket_client, the thread can't get more
        # input and is expected to terminate. This is just a safe-guard to
        # ensure it really terminates
        while True:
            t = self.thread_server
            if not t or not t.is_alive():
                break;
            t.join(0.1)


    #---------------------------------------------------------------------------
    def shutdown(self):

        self.stop_server()

        s = self.socket_client
        self.socket_client = None
        if s:
            s.close()

        # since we have closed socket_client, the thread can't get more input
        # and is expected to terminate. This is just a safe-guard to ensure it
        # really terminates
        while True:
            t = self.thread_client
            if t is None or not t.is_alive():
                break;
            self.print('join...')
            t.join(0.1)


    #---------------------------------------------------------------------------
    def connect_to_server(self, addr, port, timeout = None):

        peer = (addr, port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # try to connect to server
        while True:
            try:
                s.connect(peer)
                break

            except:
                if not timeout or timeout.has_expired():
                    raise Exception('could not connect to {}:{}'.format(addr, port))

            # using 250 ms here seems a good trade-off. Even if there is some
            # system load, we usually succeed after one retry. Using 100 ms
            # here just end up on more retries as it seems startup is either
            # quite quick or it takes some time.
            timeout.sleep(0.25)

        self.print('TCP connection established to {}:{}'.format(addr, port))
        self.socket_client = s


    #---------------------------------------------------------------------------
    def start_server(self, port):

        if self.socket_client is None:
            raise Exception('no connected to any server')

        self.socket_client = tools.Socket_With_Read_Cancellation(
                                self.socket_client)

        def socket_forwarder_loop(f_get_socket_src, f_get_socket_dst):

            cnt = 0
            max_pck = 0

            while True:

                socket_src = f_get_socket_src()
                if not socket_src:
                    # seem somebody wants to stop the loop
                    break

                data = None
                try:
                    data = socket_src.recv(self.buffer_size)
                except:
                    # something went wrong while waiting for data. We don't
                    # really care what exactly this is and simply exit the loop
                    exc_info = sys.exc_info()
                    msg = exc_info[1]
                    self.print('socket exception: {}'.format(msg))
                    traceback.print_exception(*exc_info)
                    break

                if not data:
                    # seems the socket got closed
                    break

                l = len(data)
                cnt += l
                if (l > max_pck):
                    max_pck = l

                socket_dst = f_get_socket_dst()
                if not socket_dst:
                    self.print('missing output socket, dropping {} bytes'.format(l))
                else:
                    socket_dst.sendall(data)

            # self.print('input socket closed, cnt={}, max_pck={}, terminating'.format(cnt, max_pck))



        # start reader thread
        def my_thread_client(thread):
            socket_forwarder_loop(
                lambda: self.socket_client,
                lambda: self.server_socket_client)
            # we do not close the socket here, this will happen in the cleanup
            # eventually. Until then, the socket can still be used
            self.thread_client = None


        self.thread_client = tools.run_in_thread(my_thread_client)

        peer = ('127.0.0.1', port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(peer)
            s.listen()
        except:
            s.close()
            raise Exception('could not connect to {}:{}'.format(addr, port))

        self.server_socket = s

        def my_thread_server(thread):
            (self.server_socket_client, addr) = self.server_socket.accept()
            self.print('bridge server connection from {}'.format(addr[0]))
            with self.server_socket_client:
                socket_forwarder_loop(
                    lambda: self.server_socket_client,
                    lambda: self.socket_client)
            # if the thread terminated, close all server sockets
            self.close_server_sockets()
            self.thread_server = None

        self.thread_server = tools.run_in_thread(my_thread_server)


    #---------------------------------------------------------------------------
    # get the QEMU serial port socket, if the TCP bridge is running this
    # implies shutting it down
    def get_source_socket(self):

        if self.thread_client is not None:

            self.stop_server()
            # unblock any pending socket read operation
            self.socket_client.cancel_recv()
            # wait until the thread has died
            while self.thread_client is not None:
                time.sleep(0.1)

            self.socket_client = self.socket_client.get_socket()

        return self.socket_client


#===============================================================================
#===============================================================================

class QemuProxyRunner(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, proxy_cfg_str = None):

        super().__init__(run_context, None)

        self.proxy_cfg_str = proxy_cfg_str

        self.bridge = TcpBridge(self.run_context.printer)

        self.process_qemu = None
        self.qemu_uart_network_port = 4444

        self.process_proxy = None
        self.proxy_network_port = 4445


    #---------------------------------------------------------------------------
    def is_qemu_running(self):
        return self.process_qemu and self.process_qemu.is_running()


    #---------------------------------------------------------------------------
    def is_proxy_running(self):
        return self.process_proxy and self.process_proxy.is_running()


    #---------------------------------------------------------------------------
    def start_qemu(self, print_log):

        assert( not self.is_qemu_running() )

        qemu_mapping = {
            # <plat>: ['<qemu-binary-arch>', '<qemu-machine>'],
            'imx6':      ['/opt/hc/bin/qemu-system-arm', 'sabrelite'],
            'migv':      ['qemu-system-riscv64'        , 'virt'],
            'rpi3':      ['qemu-system-aarch64'        , 'raspi3'],
            'spike':     ['qemu-system-riscv64'        , 'spike_v1.10'],
            'zynq7000':  ['/opt/hc/bin/qemu-system-arm', 'xilinx-zynq-a9'],
        }.get(self.run_context.platform, None)

        assert(qemu_mapping is not None)

        cmd_arr = [
            '{}'.format(qemu_mapping[0]),
            '-machine', qemu_mapping[1],
            '-m', 'size=1024M',
            '-nographic',
            # UART 0 is available for data exchange
            '-serial', 'tcp:localhost:{},server'.format(self.qemu_uart_network_port),
            # UART 1 is used for a syslog
            '-serial', 'file:{}'.format(self.system_log_file.name),
            '-kernel', self.run_context.system_image,
        ]

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

        if print_log:
            # now that a QEMU process exists, start the monitor thread. The
            # checker function ensures it automatically terminates when the
            # QEMU process terminates. We use an infinite timeout, as we don't
            # care when the system log file is created - it may take some time
            # if nothing is logged or it may not happen at all if nothing is
            # logged.
            self.system_log_file.start_monitor(
                printer = self.run_context.printer,
                timeout = tools.Timeout_Checker.infinite(),
                checker_func = lambda: self.is_qemu_running()
            )

        # QEMU is starting up now. If some output is redirected to files, these
        # files may not exist until there is some actual output written. There
        # is not much gain if we sleep here hoping the file pop into existence.
        # The users of these files must care of them no existing and then
        # popping into existence eventually
        # Now start a TCP server to connect to QEMU's serial port. It depends
        # on the system load how long the QEMU process takes to start and also
        # when QEMU's internal startup is done, so the QEMU is listening on the
        # port. Tests showed that without system load, timeouts are rarely
        # needed, but once there is a decent system load, even 500 ms may not
        # be enough. With 5 seconds we should be safe.
        self.bridge.connect_to_server(
            '127.0.0.1',
            self.qemu_uart_network_port,
            tools.Timeout_Checker(5))


    #---------------------------------------------------------------------------
    def start_proxy(self, print_log):

        # QEMU must be running, but not Proxy and the proxy params must exist
        assert( self.is_qemu_running() )
        assert( not self.is_proxy_running() )
        assert( self.proxy_cfg_str )

        arr = self.proxy_cfg_str.split(',')
        proxy_app = arr[0]
        serial_qemu_connection = arr[1] if (1 != len(arr)) else 'TCP'

        assert(proxy_app is not None )
        if not os.path.isfile(proxy_app):
            raise Exception('ERROR: missing proxy app: {}'.format(proxy_app))

        if (serial_qemu_connection != 'TCP'):
            raise Exception(
                'ERROR: invalid Proxy/QEMU_connection mode: {}'.format(
                    serial_qemu_connection))

        # start the bridge between QEMU and the Proxy
        self.bridge.start_server(self.proxy_network_port)

        # start the proxy and have it connect to the bridge
        cmd_arr = [
            proxy_app,
            '-c', 'TCP:{}'.format(self.proxy_network_port),
            '-t', '1' # enable TAP
        ]

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


    #----------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_start(self, print_log):

        self.start_qemu(print_log)

        # we used to have a sleep() here to give the QEMU process some fixed
        # time to start, the value was based on trial and error. However, this
        # did not really address the core problem in the end. The smarter
        # approach is forcing everybody interacting with QEMU to come up with
        # a specific re-try concept and figure out when to give up. This is
        # also closer to dealing with physical hardware, where failures and
        # non-responsiveness must be taken into account anywhere.

        if self.proxy_cfg_str:
            self.start_proxy(print_log)


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

        if self.is_qemu_running():
            #self.print('terminating QEMU...')
            self.process_qemu.terminate()
            self.process_qemu = None

        self.bridge.shutdown()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def get_serial_socket(self):
        return None if self.is_proxy_running() \
               else self.bridge.get_source_socket()
