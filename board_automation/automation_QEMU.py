#!/usr/bin/python3

import sys
import traceback
import socket
import selectors
import os
from enum import IntEnum
import socket

from . import tools
from .tools import Timeout_Checker
from . import process_tools
from . import board_automation



#===============================================================================
#===============================================================================

class TcpBridge():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer

        self.socket_client = None

        self.server_socket = None
        self.server_socket_client = None

        # the buffer size value has has been picked based on observations, the
        # largest value seen so far was 4095, which might be related to
        # - the 4 KiByte pages that ARM and RISC-V uses
        # - seL4/CAmkES based systems often use shared buffers of 4 KiByte.
        self.buffer_size = 8192

        self.sel = selectors.DefaultSelector()

        #-----------------------------------------------------------------------
        def socket_event_thread(thread):

            # this is a daemon thread that will be killed automatically when
            # the main thread dies. Thus there is no abort mechanism here
            while True:

                for key, mask in self.sel.select():

                    #self.print('callback {} {}'.format(key, mask))
                    callback = key.data

                    try:
                        callback(key.fileobj, mask)
                    except:
                        (e_type, e_value, e_tb) = sys.exc_info()
                        print('EXCEPTION in socket recv(): {}{}'.format(
                            ''.join(traceback.format_exception_only(e_type, e_value)),
                            ''.join(traceback.format_tb(e_tb))))

        tools.run_in_daemon_thread(socket_event_thread)


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print('{}: {}'.format(__class__.__name__, msg))


    #---------------------------------------------------------------------------
    def stop_server(self):

        socket_srv = self.server_socket
        if socket_srv is None:
            # there is no server running
            return

        self.server_socket = None
        self.sel.unregister(socket_srv)

        socket_src_cli = self.server_socket_client
        if socket_src_cli is not None:
            self.server_socket_client = None
            socket_src_cli.close()

        socket_srv.close()


    #---------------------------------------------------------------------------
    def shutdown(self):

        self.stop_server()

        s = self.socket_client
        if s is not None:
            self.socket_client = None
            s.close()


    #-----------------------------------------------------------------------
    # this callback is invoked when there is data to be read from the
    # server
    def callback_socket_read(
            self,
            sock,
            mask,
            cb_exp_src,
            cb_exp_dst,
            cb_closed):


        socket_src = cb_exp_src()
        if not socket_src:
            return

        if (sock != socket_src):
            return

        # read data from the socket. Since we are in a callback for a read
        # event, this is not supposed to block even if we use blocking sockets.
        # If we read no data, this means the socket has been closed. Note that
        # a non-blocking socket behaves in the same way, it throws an exception
        # if there is no data to read.
        data = None
        try:
            data = sock.recv(self.buffer_size)
        except ConnectionResetError:
            # socket already closed
            data = None

        if not data:
            cb_closed(sock)
            return

        socket_dst = cb_exp_dst()
        if not socket_dst:
            return

        socket_dst.sendall(data)


    #---------------------------------------------------------------------------
    # connect the bridge to a server, use infinite timeout by default
    def connect_to_server(self, addr, port, timeout_sec = None):

        timeout = Timeout_Checker(timeout_sec)

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

        #-----------------------------------------------------------------------
        def cb_closed(sock):
            self.sel.unregister(sock)
            self.socket_client = None


        #-----------------------------------------------------------------------
        def cb_read(sock, mask):
            self.callback_socket_read(
                sock,
                mask,
                lambda: self.socket_client,
                lambda: self.server_socket_client,
                cb_closed)

        self.sel.register(s, selectors.EVENT_READ, cb_read)


    #---------------------------------------------------------------------------
    def start_server(self, port):

        #-----------------------------------------------------------------------
        def cb_closed(sock):
            self.sel.unregister(sock)
            self.server_socket_client = None


        #-----------------------------------------------------------------------
        def cb_read(sock, mask):
            self.callback_socket_read(
                sock,
                mask,
                lambda: self.server_socket_client,
                lambda: self.socket_client,
                cb_closed)


        #-----------------------------------------------------------------------
        def cb_accept(sock, mask):
            if self.server_socket != sock:
                return

            (s, addr) = sock.accept()
            self.print('connection from {}'.format(addr))
            self.server_socket_client = s
            self.sel.register(s, selectors.EVENT_READ, cb_read)


        if self.socket_client is None:
            raise Exception('not connected to any server')

        peer = ('127.0.0.1', port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # if we execute the test script in the container in quick succession
        # the second execution would fail due to an unavailable port.
        # Setting it as reusable, allows us to avoid this failure case.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(peer)
        except:
            s.close()
            raise Exception('could not create server socket on port {}'.format(port))

        self.server_socket = s
        s.listen(0)

        self.sel.register(s, selectors.EVENT_READ, cb_accept)


    #---------------------------------------------------------------------------
    # get the QEMU serial port socket, if the TCP bridge is running this
    # implies shutting it down
    def get_source_socket(self):

        self.stop_server()

        sock = self.socket_client
        if sock is None:
            return None

        # unregistering throws a KeyError exception if the socket is not
        # registered. This can happen, because get_source_socket() may be
        # called multiple times during a test run.
        try:
            self.sel.unregister(sock)
        except KeyError:
            # if source_socket() has been called before, the socket was already
            # unregistered then. So we can ignore this exception.
            pass

        return sock


#===============================================================================
#===============================================================================
import threading

class QemuProxyRunner(board_automation.System_Runner):
    # to allow multi instance of this class we need to avoid insisting on the
    # same port. Therefore a base is established here but the port number used
    # is calculated every time an instance gets created (see code below). At the
    # moment we can consider this as a workaround. In the future we will
    # implement a different way of communication for qemu (see SEOS-1845)
    qemu_uart_network_port  = 4444
    port_cnt_lock = threading.Lock()

    #---------------------------------------------------------------------------
    def __init__(self, run_context, proxy_cfg_str = None, additional_params = None):

        super().__init__(run_context, None)

        self.sd_card_size = run_context.sd_card_size
        self.proxy_cfg_str = proxy_cfg_str
        self.additional_params = additional_params

        # attach to QEMU UART via TCP bridge
        self.bridge = TcpBridge(self.run_context.printer)

        self.process_qemu = None
        self.process_proxy = None

        QemuProxyRunner.port_cnt_lock.acquire()
        base_port = QemuProxyRunner.qemu_uart_network_port
        QemuProxyRunner.qemu_uart_network_port += 2
        QemuProxyRunner.port_cnt_lock.release()

        self.qemu_uart_network_port = base_port
        self.proxy_network_port     = base_port + 1

        self.qemu_uart_log_host     = 'localhost'
        self.qemu_uart_log_port     = base_port + 2

    #---------------------------------------------------------------------------
    def is_qemu_running(self):
        return self.process_qemu and self.process_qemu.is_running()


    #---------------------------------------------------------------------------
    def is_proxy_running(self):
        return self.process_proxy and self.process_proxy.is_running()


    #---------------------------------------------------------------------------
    def send_data_to_uart(self, data):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.qemu_uart_log_host, self.qemu_uart_log_port))
            s.sendall(str.encode(data))


    #---------------------------------------------------------------------------
    def start_qemu(self, print_log):

        #-----------------------------------------------------------------------
        class qemu_app_wrapper:
            #-------------------------------------------------------------------
            def __init__(self, binary, machine, cpu, memory):
                self.binary = binary
                self.machine = machine
                self.cpu = cpu
                self.cores = None
                self.memory = memory

                # 'kernel' is the common option to boot an OS like Linux, 'bios'
                # is machine specific to load firmware. On RISC-V, 'bios' allows
                # booting the system in M-Mode and install a custom SBI, while
                # 'kernel' will make QEMU use an OpenSBI firmware that comes
                # with QEMU and boot the given OS in S-Mode.
                self.bios = None
                self.kernel = None

                # By default this is off, since we currently don't have any
                # platform that uses this.
                self.graphic = False

                # enable for instruction tracing
                self.singlestep = False

                # SD card
                self.sd_card_image = None
                self.sd_card_size = None # set to truncate sd_card_image

                # There can be multiple serial ports. Python guarantees the
                # order is preserved when adding elements to an array.
                self.serial_ports = []

                self.params = [] # additional parameters

            #-------------------------------------------------------------------
            def add_params(self, *argv):
                for arg in argv:
                    if isinstance(arg, list):
                        self.params.extend(arg)
                    else:
                        self.params.append(arg)


            #-------------------------------------------------------------------
            def sys_log_setup(self, sys_log_path, host, port, id):
                # In adition to outputting the guest system log to a log file,
                # we are openning a 2-way TCP socket connected to the same
                # serial device that allows the test suite to communicate with
                # the guest during the test execution.
                self.add_params([
                    '-chardev',
                    'socket,id=char{},port={},host={},server,nowait,logfile={},signal=off'.format(
                        id, port, host, sys_log_path)])
                self.serial_ports += ['chardev:char{}'.format(id)]


            #-------------------------------------------------------------------------------
            class Additional_Param_Type(IntEnum):
                VALUE       = 0,
                BINARY_IMG  = 1,


            #-------------------------------------------------------------------------------
            def param_mem_blob(self, address, blob):
                return ['-device', 'loader,addr={},file={},'.format(address, blob)]


            #-------------------------------------------------------------------------------
            def param_mem_value(self, address, value):
                return ['-device', 'loader,addr={},data={},data-len=4'.format(address, value)]


            #-------------------------------------------------------------------
            def start(
                self,
                log_file_stdout,
                log_file_stderr,
                aditional_params = None,
                printer = None,
                print_log = False):

                cmd_arr = []

                if self.machine:
                    cmd_arr += ['-machine', self.machine]

                if self.cpu:
                    cmd_arr += ['-cpu', self.cpu]

                if self.cores:
                    cmd_arr += ['-smp', str(self.cores)]

                if self.memory:
                    cmd_arr += ['-m', 'size={}M'.format(self.memory)]

                if not self.graphic:
                    cmd_arr += ['-nographic']

                if self.singlestep:
                    cmd_arr += ['-singlestep']

                if self.kernel:
                    cmd_arr += ['-kernel', self.kernel]

                if self.bios:
                    cmd_arr += ['-bios', self.bios]

                # connect all serial ports
                for p in self.serial_ports:
                    cmd_arr += ['-serial', p if p else 'null']

                if self.sd_card_image:
                    if (self.machine in ['spike', 'sifive_u']):
                        if printer:
                            printer.print(
                                'QEMU: ignoring SD card, not supported for {}'.format(
                                    self.machine))
                    else:
                        if self.sd_card_size:
                            # ToDo: maybe we should create a copy here and not
                            #       modify the original file...
                            with open(self.sd_card_image, 'wb') as sd_card_image:
                                sd_card_image.truncate(self.sd_card_size)
                        cmd_arr += [
                            '-drive',
                            'file={},format=raw,id=mycard'.format(self.sd_card_image),
                            '-device', 'sd-card,drive=mycard'
                        ]

                if aditional_params:
                    for param in aditional_params:
                        if param[2] == self.Additional_Param_Type.VALUE:
                            cmd_arr += self.param_mem_value(param[0], param[1])
                        elif param[2] == self.Additional_Param_Type.BINARY_IMG:
                            cmd_arr += self.param_mem_blob(param[0], param[1])
                        else:
                            printer.print('QEMU: additional parameter type {} \
                                not supported!'.format(param[2]))

                cmd = [ self.binary ] + cmd_arr + self.params

                if printer:
                    printer.print('QEMU: {}'.format(' '.join(cmd)))

                process = process_tools.ProcessWrapper(
                            cmd,
                            log_file_stdout = log_file_stdout,
                            log_file_stderr = log_file_stderr,
                            printer = printer,
                            name = 'QEMU' )

                process.start(print_log)

                return process


        #-----------------------------------------------------------------------
        class qemu_aarch32(qemu_app_wrapper):
            def __init__(self, machine, cpu, memory):
                super().__init__(
                    '/opt/hc/bin/qemu-system-arm',
                    machine, cpu, memory)


        #-----------------------------------------------------------------------
        class qemu_aarch64(qemu_app_wrapper):
            def __init__(self, machine, cpu, memory):
                super().__init__('qemu-system-aarch64', machine, cpu, memory)


        #-----------------------------------------------------------------------
        class qemu_riscv64(qemu_app_wrapper):
            def __init__(self, machine, cpu, memory):
                super().__init__('qemu-system-riscv64', machine, cpu, memory)
                # qemu-system-riscv64
                #   -machine <'list' or one from the list>
                #     none          empty machine
                #     sifive_e      SiFive E SDK
                #     sifive_u      SiFive U SDK
                #     spike         (default)
                #     spike_v1.10   (Privileged ISA v1.10)
                #     spike_v1.9.1  (Privileged ISA v1.9.1)
                #     virt          VirtIO board
                #
                #     dump the device tree with "<machine>,dumpdtb=dtb.out"
                #
                #   -cpu <'help' or one form the list>
                #     any
                #     rv64
                #     rv64gcsu-v1.10.0
                #     rv64gcsu-v1.9.1
                #     rv64imacu-nommu
                #     sifive-e51
                #     sifive-u54

        #-----------------------------------------------------------------------
        class qemu_riscv32(qemu_app_wrapper):
            def __init__(self, machine, cpu, memory):
                super().__init__('qemu-system-riscv32', machine, cpu, memory)


        #-----------------------------------------------------------------------
        class qemu_zcu102(qemu_app_wrapper):
            def __init__(self, cpu, memory, res_path, dev_path):
                super().__init__('/opt/xilinx-qemu/bin/qemu-system-aarch64',
                                    None, cpu, memory)

                if res_path == None:
                    raise Exception('ERROR: qemu_zcu102 requires the resource path')

                self.add_params([
                    '-machine', 'arm-generic-fdt',
                    '-dtb', os.path.join(res_path, 'zcu102-arm.dtb'),
                    '-device', 'loader,file={},cpu-num=0'.format(os.path.join(res_path, 'bl31.elf')),
                    '-device', 'loader,file={}'.format(os.path.join(res_path, 'u-boot.elf')),
                    '-global', 'xlnx,zynqmp-boot.cpu-num=0',
                    '-global', 'xlnx,zynqmp-boot.use-pmufw=true',
                    '-machine-path', dev_path])


        #-----------------------------------------------------------------------
        class qemu_microblaze(qemu_app_wrapper):
            def __init__(self, cpu, memory, res_path, dev_path):
                super().__init__('/opt/xilinx-qemu/bin/qemu-system-microblazeel',
                                    None, cpu, memory)

                if res_path == None:
                    raise Exception('ERROR: qemu_microblaze requires the resource path')

                self.add_params([
                    '-machine', 'microblaze-fdt',
                    '-dtb', os.path.join(res_path, 'zynqmp-pmu.dtb'),
                    '-kernel', os.path.join(res_path, 'pmu_rom_qemu_sha3.elf'),
                    '-device', 'loader,file={}'.format(os.path.join(res_path, 'pmufw.elf')),
                    '-machine-path', dev_path])


        assert( not self.is_qemu_running() )

        qemu = {
            'sabre':    qemu_aarch32('sabrelite', None, 1024),
            'migv':     qemu_riscv64('virt', None, 1024),
            'hifive':   qemu_riscv64('sifive_u', None, 8192),
            'rpi3':     qemu_aarch64('raspi3', None, 1024),
            'spike64':  qemu_riscv64('spike', 'rv64', 4095),
            'spike32':  qemu_riscv32('spike', 'rv32', 1024),
            'zynq7000': qemu_aarch32('xilinx-zynq-a9', None, 1024),
            'zynqmp':   qemu_zcu102(None, 4096,
                                    os.path.join(
                                        self.run_context.resource_dir,
                                        'zcu102_sd_card'),
                                    self.run_context.log_dir),
        }.get(self.run_context.platform, None)

        assert(qemu is not None)

        if self.run_context.platform in ['spike32', 'spike64']:
            # Seems older QEMU versions do not support the 'bios' parameter, so
            # we can't use
            #   qemu.bios = self.run_context.system_image
            # and have to stick to loading a kernel
            qemu.kernel = self.run_context.system_image
        elif self.run_context.platform in ['hifive']:
            qemu.bios = self.run_context.system_image
            # The platform has 1x E51 and 4x U54. In QEMU, the E51 and one U54
            # always exist, setting qemu.cores = 3,4,5 can be used to activate
            # additional U54 cores.
            # qemu.cores = 5
        else:
            qemu.kernel = self.run_context.system_image

        #qemu.singlestep = True
        #qemu.add_params('-d', 'in_asm,cpu') # logged to stderr
        #qemu.add_params('-d', 'in_asm') # logged to stderr
        #qemu.add_params('-D', 'qemu_log.txt')

        # Serial port usage is platform specific. On platforms with one serial
        # port only, this one is used for syslog. If there are multiple UARTs,
        # some platforms have the syslog on UART_0 and UART_1 is available for
        # data exchange. Others do it the other way around, UART_0 is available
        # for data exchange and UART_1 is used for the syslog.
        has_syslog_on_uart_1 = self.run_context.platform in ['sabre',
                                                             'zynq7000']
        has_data_uart = (self.run_context.platform in ['sabre',
                                                       'zynq7000',
                                                       'zynqmp',
                                                       'hifive'])
        assert(0 == len(qemu.serial_ports))
        if not has_syslog_on_uart_1:
            # UART 0 is syslog
            qemu.sys_log_setup(
                self.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                0)

        if (has_data_uart):
            # UART 0 or UART 1 is used for data
            qemu.serial_ports += ['tcp:localhost:{},server'.format(self.qemu_uart_network_port)]
        elif has_syslog_on_uart_1:
            # UART 0 must be a dummy in this case
            assert(0 == len(qemu.serial_ports))
            qemu.serial_ports += ['null']

        if has_syslog_on_uart_1:
            assert(1 == len(qemu.serial_ports))
            # UART 1 is syslog
            qemu.sys_log_setup(
                self.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                1)

        # SD card (might be ignored if target does not support this)
        if self.sd_card_size and (self.sd_card_size > 0):
            qemu.sd_card_image = self.get_log_file_fqn('sdcard1.img')
            qemu.sd_card_size = self.sd_card_size

        # Running test on the zynqmp requires 2 QEMU instances and passing
        # additional parameters.
        if self.run_context.platform == 'zynqmp':
            # Since we are booting from the SD card the kernel image is not
            # passed directly
            qemu.kernel = None

            # We do not want to truncate the SD card to a specific size
            qemu.sd_card_size = None

            # Creating an SD image that contains the system binary which will
            # be booted by U-Boot
            tools.create_sd_img(qemu.sd_card_image,
                                128*1024*1024, # 128 MB
                                [(self.run_context.system_image, 'os_image.elf')])

            # Initializing the MicroBlaze based PMU QEMU instance
            qemu_pmu_instance = qemu_microblaze(None, None,
                                                os.path.join(
                                                    self.run_context.resource_dir,
                                                    'zcu102_sd_card'),
                                                self.run_context.log_dir)

            # Starting the MicroBlaze based PMU QEMU instance
            self.process_qemu_pmu_instance = qemu_pmu_instance.start(
                        log_file_stdout = self.get_log_file_fqn('qemu_pmu_out.txt'),
                        log_file_stderr = self.get_log_file_fqn('qemu_pmu_err.txt'),
                        printer = self.run_context.printer,
                        print_log = print_log
                    )

        # start QEMU
        self.process_qemu = qemu.start(
                                log_file_stdout = self.get_log_file_fqn('qemu_out.txt'),
                                log_file_stderr = self.get_log_file_fqn('qemu_err.txt'),
                                aditional_params = self.additional_params,
                                printer = self.run_context.printer,
                                print_log = print_log
                            )

        if print_log:
            # now that a QEMU process exists, start the monitor thread. The
            # checker function ensures it automatically terminates when the
            # QEMU process terminates. We use an infinite timeout, as we don't
            # care when the system log file is created - it may take some time
            # if nothing is logged or it may not happen at all if nothing is
            # logged.
            self.system_log_file.start_monitor(
                printer = self.run_context.printer,
                timeout = Timeout_Checker.infinite(),
                checker_func = lambda: self.is_qemu_running()
            )

        # QEMU is starting up now. If some output is redirected to files, these
        # files may not exist until there is some actual output written. There
        # is not much gain if we sleep now hoping the files pop into existence.
        # The users of these files must handle the fact that they don't exist
        # at first and pop into existence eventually

        if has_data_uart:
            # Starting a TCP server that connects to QEMU's serial port. It
            # depends on the system load how long the QEMU process itself takes
            # to start and when QEMU's internal startup is done, so it is
            # listening on the port. Tests showed that without system load,
            # timeouts are rarely needed, but once there is a decent system
            # load, even 500 ms may not be enough. With 5 seconds we should be
            # safe.
            self.bridge.connect_to_server(
                '127.0.0.1',
                self.qemu_uart_network_port,
                Timeout_Checker(5))


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
