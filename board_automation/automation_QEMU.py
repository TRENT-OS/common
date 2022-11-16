#!/usr/bin/python3

import sys
import threading
import traceback
import socket
import selectors
import os
from enum import IntEnum
import socket
import time

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

                    #self.print(f'callback {key} {mask}')
                    callback = key.data

                    try:
                        callback(key.fileobj, mask)
                    except Exception as e:
                        (e_type, e_value, e_tb) = sys.exc_info()
                        self.print(f'EXCEPTION in socket callback: {e}\n'
                                   ''.join(traceback.format_exception_only(e_type, e_value)) +
                                   '\nCall stack:\n' +
                                   ''.join(traceback.format_tb(e_tb)))

        tools.run_in_thread(socket_event_thread)


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(f'{__class__.__name__}: {msg}')


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

            except Exception as e:
                if not timeout or timeout.has_expired():
                    self.print(f'EXCEPTION connecting socket: {e}')
                    raise Exception(f'could not connect to {addr}:{port}')

            # using 250 ms here seems a good trade-off. Even if there is some
            # system load, we usually succeed after one retry. Using 100 ms
            # here just end up on more retries as it seems startup is either
            # quite quick or it takes some time.
            timeout.sleep(0.25)

        self.print(f'TCP connection established to {addr}:{port}')
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
            self.print(f'connection from {addr}')
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
            raise Exception(f'could not create server socket on port {port}')

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

class QEMU_AppWrapper:

    #---------------------------------------------------------------------------
    def __init__(self, params_dict = dict()):

        self.config = {
            'qemu-bin': None,
            'machine': None,
            'dtb': None,
            'cpu': None,
            'cores': None,
            'memory': None,
            # currently we don't have any platform that has a monitor
            'graphic': None,
            # 'kernel' is the common option to boot an OS like Linux,
            # 'bios' is machine specific to load firmware. On RISC-V,
            # 'bios' allows booting the system in M-Mode and install a
            # custom SBI, while 'kernel' will make QEMU use an OpenSBI
            # firmware that comes with QEMU and boots the given OS in
            # S-Mode.
            'bios': None,
            'kernel':  None,
            # enable for instruction tracing
            'singlestep': False,
            # There can be multiple drives, devices, SD-Card or NICs.
            # Python guarantees the order is preserved when adding
            # elements to an array.
            'drives': [],
            'devices': [],
            'serial_ports': [],
            # Defaults are set, add or overwrite custom config. Python support
            # for merging dictionaries:
            #   Python >= 3.9:  z = x | y
            #   Python >= 3.5:  z = {**x, **y}
            #   else:           z = x.copy(); z.update(y); return z
            **params_dict
        }

        # SD card devices based on images need unique numbers.
        self.num_sdcard_images = 0

        self.raw_params = []

    #---------------------------------------------------------------------------
    def add_params(self, *argv):
        for arg in argv:
            if isinstance(arg, list):
                self.raw_params.extend(arg)
            else:
                self.raw_params.append(arg)


    #---------------------------------------------------------------------------
    def serialize_param_dict(self, arg_dict):
        # Python 3.6 made the standard dict type maintain the insertion
        # order. With older versions the iteration order is random.
        return None if arg_dict is None \
               else ','.join([
                    (f'{key}' if value is None \
                        else f'{key}={value}')
                    for (key, value) in arg_dict.items()
               ])


    #---------------------------------------------------------------------------
    def add_serial_port(self, port):
        # A list preserves the order of added elements
        self.config['serial_ports'] += [port]


    #---------------------------------------------------------------------------
    def add_drive(self, param_dict):
        # A list preserves the order of added elements
        self.config['drives'] += [param_dict]



    #---------------------------------------------------------------------------
    def add_device(self, dev_type, sub_type, param_dict = None):
        # A list preserves the order of added elements
        self.config['devices'] += [ (dev_type, sub_type, param_dict) ]


    #---------------------------------------------------------------------------
    def add_dev_nic_none(self):
        # Any dummy NIC is just another device
        self.add_device('nic', 'none', None)


    #---------------------------------------------------------------------------
    def add_dev_nic_tap(self, tap, param_dict = dict()):
        full_param_dict = {
            'ifname': tap,
            'script': 'no'
        }
        full_param_dict.update(param_dict)
        # Any TAP NIC is just another device
        self.add_device('nic', 'tap', full_param_dict)


    #---------------------------------------------------------------------------
    def add_dev_char_socket(self, param_dict):
        assert(len(param_dict) > 0)  # there must be parameters
        # Any chardevice based on a socket is basically just another
        # device
        self.add_device('chardev', 'socket', param_dict)


    #---------------------------------------------------------------------------
    def add_sdcard_from_image(self, sd_card_image):
        dev_id = f'sdcardimg{self.num_sdcard_images}'
        self.num_sdcard_images += 1
        # Add a drive with the file and connect the SD-Card to it.
        self.add_drive({
            'id': dev_id,
            'file': sd_card_image,
            'format': 'raw',
        })
        self.add_device('device', 'sd-card', {'drive': dev_id})


    #---------------------------------------------------------------------------
    def add_dev_loader(self, param_dict):
        assert(len(param_dict) > 0)  # there must be loader parameters
        self.add_device('device', 'loader', param_dict)


    #---------------------------------------------------------------------------
    def init_memory_at(self, address, value, param_dict = dict()):
        full_param_dict = {
            'addr': address,
            'data': value,
            'data-len': 4
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def load_blob(self, address, filename, param_dict = dict()):

        if not os.path.isfile(filename):
            raise Exception(f'Missing blob file: {filename}')

        full_param_dict = {
            'addr': address,
            'file': filename
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def load_elf(self, filename, param_dict = dict()):

        if not os.path.isfile(filename):
            raise Exception(f'Missing ELF file: {filename}')

        full_param_dict = {
            'file': filename
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def sys_log_setup(self, sys_log_path, host, port, id):
        # In addition to outputting the guest system log to a log file,
        # we are opening a 2-way TCP socket connected to the same serial
        # device that allows the test suite to communicate with the
        # guest during the test execution.
        dev_id = f'chardev{id}'
        self.add_dev_char_socket({
            'id': dev_id,
            'host': host,
            'port': port,
            'server': 'on',
            'wait': 'off',
            'logfile': sys_log_path,
            'signal': 'off'
        })
        self.add_serial_port(f'chardev:{dev_id}')


    #---------------------------------------------------------------------------
    def get_machine(self):
        param = self.config.get('machine', None)
        if param and isinstance(param, list):
            assert(isinstance(param[0], str))
            assert(isinstance(param[1], dict)) # may have 'dumpdtb=<filename>'
            param = param[0]
        return param

    #---------------------------------------------------------------------------
    def get_qemu_start_cmd_params_array(
        self,
        printer = None):

        cfg = self.config.copy()

        param = cfg.pop('qemu-bin', None)
        if param is None:
            printer.print('no binary given for QEMU')
            return None
        cmd_arr = [ param ]

        param = cfg.pop('machine', None)
        if param is None:
            printer.print('no machine given for QEMU')
            return None
        if isinstance(param, list):
            assert(isinstance(param[0], str))
            assert(isinstance(param[1], dict)) # may have 'dumpdtb=<filename>'
            param = param[0] + ',' + self.serialize_param_dict(param[1])
        cmd_arr += ['-machine', param]

        param = cfg.pop('dtb', None)
        if param:
            cmd_arr += ['-dtb', param]

        param = cfg.pop('cpu', None)
        if param:
            cmd_arr += ['-cpu', param]

        param = cfg.pop('cores', None)
        if param:
            cmd_arr += ['-smp', str(param)]

        param = cfg.pop('memory', None)
        if param:
            cmd_arr += ['-m', f'size={param}M']

        param = cfg.pop('graphic', False)
        if not param: # works also is set to None
            cmd_arr += ['-nographic']

        param = cfg.pop('singlestep', False)
        if param: # works also is set to None
            cmd_arr += ['-singlestep']

        param = cfg.pop('kernel', None)
        if param:
            cmd_arr += ['-kernel', param]

        param = cfg.pop('bios', None)
        if param:
            cmd_arr += ['-bios', param]

        # SD-Card images are basically a device/drive combination
        param = cfg.pop('sdcard_images', [])
        for i, img in enumerate(param):
            dev_id = f'sdcardimg{i}'
            self.add_drive({
                'id': dev_id,
                'file': sd_card_image,
                'format': 'raw',
            })
            self.add_dev_sdcard({'drive': dev_id})

        param = cfg.pop('drives', [])
        for param_dict in param:
            assert(len(param_dict) > 0)  # there must be parameters
            cmd_arr += ['-drive', self.serialize_param_dict(param_dict)]

        param = cfg.pop('devices', [])
        for (dev_type, sub_type, param_dict) in param:
            cmd_arr += [
                '-' + dev_type,
                sub_type if param_dict is None \
                else ','.join([
                    sub_type,
                    self.serialize_param_dict(param_dict)
                ])
            ]

        # connect all serial ports
        param = cfg.pop('serial_ports', [])
        for p in param:
            cmd_arr += ['-serial', p if p else 'null']

        if cfg:
            if printer:
                printer.print(f'QEMU: unsupported config: {cfg}')
            return None

        return cmd_arr + self.raw_params


    #---------------------------------------------------------------------------
    def start(
        self,
        log_file_stdout,
        log_file_stderr,
        additional_params = None,
        printer = None,
        print_log = False):

        if additional_params:
            for param in additional_params:
                if param[2] == self.Additional_Param_Type.VALUE:
                    self.init_memory_at(param[0], param[1])
                elif param[2] == self.Additional_Param_Type.BINARY_IMG:
                    self.load_blob(param[0], param[1])
                else:
                    printer.print(f'QEMU: additional parameter type {param[2]}'
                                   ' not supported!')

        cmd_param_array = self.get_qemu_start_cmd_params_array(printer)

        if cmd_param_array is None:
            printer.print('could not create QEMU command line')
            return None

        if printer:
            printer.print(f'QEMU: {" ".join(cmd_param_array)}')

        process = process_tools.ProcessWrapper(
                    cmd_param_array,
                    log_file_stdout = log_file_stdout,
                    log_file_stderr = log_file_stderr,
                    printer = printer,
                    name = 'QEMU' )

        process.start(print_log)

        return process


#-------------------------------------------------------------------------------
class QEMU_zcu102(QEMU_AppWrapper):

    def __init__(self, param_dict = dict()):
        super().__init__(
            {
                'qemu-bin': '/host/qemu/xilinx-v2022.1/qemu-system-aarch64',
                'machine':  'arm-generic-fdt',
                # Defaults are set, add or overwrite custom config.
                **param_dict
            })

        self.qemu_pmu = QEMU_AppWrapper({
            'qemu-bin': '/host/qemu/xilinx-v2022.1/qemu-system-microblazeel',
            'machine':  'microblaze-fdt',
        })


    #---------------------------------------------------------------------------
    # ToDo: generalize this hack and put a setup() in QEMU_AppWrapper
    def setup(self, res_dir, log_dir):

        if not os.path.isdir(res_dir):
            raise Exception(f'res_dir Directory {res_dir} does not exist!')

        if not os.path.isdir(log_dir):
            raise Exception(f'log_dir Directory {log_dir} does not exist!')

        # PE (ARM cluster) software
        pe_dtb          = os.path.join(res_dir, 'zcu102-arm.dtb')
        pe_bl_elf       = os.path.join(res_dir, 'bl31.elf')
        pe_u_boot_elf   = os.path.join(res_dir, 'u-boot.elf')
        # PMU (MicroBlaze) software
        pmu_dtb        = os.path.join(res_dir, 'zynqmp-pmu.dtb')
        pmu_kernel_elf = os.path.join(res_dir, 'pmu_rom_qemu_sha3.elf')
        pmu_fw_elf     = os.path.join(res_dir, 'pmufw.elf')

        if not os.path.isfile(pe_dtb) or \
           not os.path.isfile(pe_bl_elf) or \
           not os.path.isfile(pe_u_boot_elf) or \
           not os.path.isfile(pmu_dtb) or \
           not os.path.isfile(pmu_kernel_elf) or \
           not os.path.isfile(pmu_fw_elf):
            raise Exception('The resource directory does not contain \
                             all necessary files to start QEMU')

        # We don't pass a kernel to QEMU, because the zcu102 platform has
        # "ROM code" that can boot U-Boot from an SD card. A special U-Boot
        # version has been created that loads os_image.elf then.
        sd_card_image = os.path.join(log_dir, 'sdcard1.img')
        # ToDo: 128 MiB seems a lot if we just store os_image.elf there.
        tools.create_sd_img(
            sd_card_image,
            128*1024*1024, # 128 MiB
            [(self.run_context.system_image, 'os_image.elf')])
        qemu.config['kernel'] = None
        seld.add_sdcard_from_image(sd_card_image)
        self.config['dtb'] = pe_dtb
        self.add_params(
            '-global', 'xlnx,zynqmp-boot.cpu-num=0',
            '-global', 'xlnx,zynqmp-boot.use-pmufw=true',
            '-machine-path', log_dir)
        self.load_elf(pe_bl_elf, {'cpu-num': 0})
        self.load_elf(pe_u_boot_elf)

        self.qemu_pmu.config['dtb'] = pmu_dtb
        self.qemu_pmu.config['kernel'] = pmu_kernel_elf
        self.qemu_pmu.add_params('-machine-path', log_dir)
        self.qemu_pmu.load_elf(pmu_fw_elf)


    #---------------------------------------------------------------------------
    def start(
        self,
        log_file_stdout,
        log_file_stderr,
        additional_params = None,
        printer = None,
        print_log = False):

        def pmu_logfile(parent_log_file, channel):
            return os.path.join(
                    os.path.dirname(parent_log_file),
                    f'qemu_pmu_{channel}.txt')

        # start PMU (MicroBlaze) instance first
        process_qemu_pmu = self.qemu_pmu.start(
            log_file_stdout = pmu_logfile(log_file_stdout, 'out'),
            log_file_stderr = pmu_logfile(log_file_stderr, 'err'),
            additional_params = None,
            printer = printer,
            print_log = print_log
        )

        # start PE (ARM Cluster) instance afterwards
        process_qemu_pe = super().start(
            log_file_stdout = log_file_stdout,
            log_file_stderr = log_file_stderr,
            additional_params = additional_params,
            printer = printer,
            print_log = print_log
        )

        class Process_qemu_zcu102_microblaze():
            def __init__(self, processes):
                self.processes = processes
            def is_running(self):
                return all([p.is_running() for p in self.processes])
            def terminate(self):
                for p in self.processes: p.terminate()

        return Process_qemu_zcu102_microblaze([process_qemu_pe, process_qemu_pmu])


#-------------------------------------------------------------------------------
def get_qemu(target, printer=None):

    qemu_cfgs = {
        'sabre': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  'sabrelite',
            'memory':   1024
        },
        'migv_qemu': {
            'qemu-bin': '/opt/hc/migv/bin/qemu-system-riscv64',
            'machine': 'mig-v',
            'memory':   1024,
        },
        'hifive': {
            'qemu-bin': 'qemu-system-riscv64',
            'machine':  'sifive_u',
            'memory':   8192,
            # Core setting works as:
            #   1: 1x U54, 1x E51
            #   2: 1x U54, 1x E51
            #   3  2x U54, 1x E51
            #   4: 3x U54, 1x E51
            #   5: 4x U54, 1x E51
            # The qemu-system-riscv32 sifive_u uses U34/E31 cores
            'cores':    5
        },
        'rpi3': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'raspi3',
            'memory':   1024,
        },
        'spike64': {
            'qemu-bin': 'qemu-system-riscv64',
            'machine':  'spike',
            'cpu':      'rv64',
            'memory':   4095,
        },
        'spike32': {
            'qemu-bin': 'qemu-system-riscv32',
            'machine':  'spike',
            'cpu':      'rv32',
            'memory':   1024,
        },
        'zynq7000': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  'xilinx-zynq-a9',
            'memory':   1024,
        },
        'zynqmp': {
            'qemu-bin': QEMU_zcu102, # this is really the class, not an instance
            'memory':   4096,
        },
        'qemu-arm-virt-a15': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  ['virt', {
                'secure':         'off',
                'virtualization': 'on',
                'highmem':        'off',
                'gic-version':    '2',
            }],
            'cpu':      'cortex-a15',
            'memory':   2048,
        },
        'qemu-arm-virt-a53': {
            'qemu-bin':   'qemu-system-aarch64',
            'machine':    ['virt', {
                'secure':         'off',
                'virtualization': 'on',
                'highmem':        'on',
                'gic-version':    '2',
            }],
            'cpu':      'cortex-a53',
            'memory':   2048,
        },
        'qemu-arm-virt-a57': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'virt',
            'cpu':      'cortex-a57',
            'memory':   2048,
        },
        'qemu-arm-virt-a72': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'virt',
            'cpu':      'cortex-a72',
            'memory':   2048,
        },
    }

    if not target:
        if printer:
            printer.print('empty QEMU target')
        return None

    qemu_cfg = qemu_cfgs.get(target)
    if not qemu_cfg:
        if printer:
            printer.print(f'unsupported QEMU target: "{target}"')
        return None

    qemu_bin = qemu_cfg['qemu-bin'];
    if not qemu_cfg:
        if printer:
            printer.print(f'no binary for QEMU target: "{target}"')
        return None

    if isinstance(qemu_bin, str):
        qemu_cfg['qemu-bin'] = qemu_bin
        return QEMU_AppWrapper(qemu_cfg)

    # Instead of a string, a class reference can also be used. The actual
    # instantiation only happens if this is also the target that the tests used.
    # The try-except block is needed because issubclass() throws an exception if
    # the parameter is not a class. Doing a check inspect.isclass() first could
    # avoid the try-except.
    try:
        if issubclass(qemu_bin, QEMU_AppWrapper):
            return qemu_bin()
    except TypeError:
        pass

    # An instance can also be specified. However, adding instances to qemu_cfgs
    # should be avoided because the instantiation will always happen, even if
    # the tar is running for a different target and thus the instance is never
    # used.
    if isinstance(qemu_bin, QEMU_AppWrapper):
        return qemu_bin

    # Don't know which QEMU to use.
    if printer:
        printer.print(f'unsupported binary for QEMU target: "{target}", "{qemu_bin}"')

    return None


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
class Additional_Param_Type(IntEnum):
    VALUE       = 0,
    BINARY_IMG  = 1,


#-------------------------------------------------------------------------------
class QemuProxyRunner(board_automation.System_Runner):
    # to allow multi instance of this class we need to avoid insisting on the
    # same port. Therefore a base is established here but the port number used
    # is calculated every time an instance gets created (see code below). At the
    # moment we can consider this as a workaround. In the future we will
    # implement a different way of communication for QEMU (see SEOS-1845)
    qemu_uart_network_port  = 4444
    port_cnt_lock = threading.Lock()

    #---------------------------------------------------------------------------
    def __init__(self, run_context, proxy_cfg_str = None, additional_params = None):

        super().__init__(run_context, None)

        self.sd_card_size = run_context.sd_card_size
        self.proxy_cfg_str = proxy_cfg_str
        self.additional_params = additional_params

        # attach to QEMU UART via TCP bridge
        self.bridge = TcpBridge(printer=self.get_printer())

        self.process_qemu = None
        self.process_proxy = None

        QemuProxyRunner.port_cnt_lock.acquire()
        base_port = QemuProxyRunner.qemu_uart_network_port
        QemuProxyRunner.qemu_uart_network_port += 4
        QemuProxyRunner.port_cnt_lock.release()

        self.qemu_uart_network_port = base_port
        self.proxy_network_port     = base_port + 1

        self.qemu_uart_log_host     = 'localhost'
        self.qemu_uart_log_port     = base_port + 2


    #---------------------------------------------------------------------------
    def get_printer(self):
        if not self.run_context:
            return None

        return self.run_context.printer


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.get_printer()
        if printer:
            printer.print(msg)


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
    def send_file_to_uart(self, file):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.qemu_uart_log_host, self.qemu_uart_log_port))
            with open(file, 'r') as srec:
                while True:
                    srec_line = srec.readline()
                    if len(srec_line) == 0:
                        break
                    else:
                        for byte in srec_line:
                            s.send(bytes(byte, 'ascii'))
                            # Empirically set delay between individual bytes
                            # long enough to eliminate transmission errors
                            time.sleep(0.01)

                    # Empirically set delay between individual records
                    # long enough to eliminate transmission errors
                    time.sleep(0.15)


    #---------------------------------------------------------------------------
    def start_qemu(self, print_log):

        assert( not self.is_qemu_running() )
        qemu = get_qemu(
                target  = self.run_context.platform,
                printer = self.get_printer())
        assert( qemu is not None )

        #qemu.config['singlestep'] = True
        #qemu.add_params('-d', 'in_asm,cpu') # logged to stderr
        #qemu.add_params('-d', 'in_asm') # logged to stderr
        #qemu.add_params('-D', 'qemu_log.txt')

        if self.run_context.platform in ['hifive', 'migv_qemu']:
            qemu.config['bios'] = self.run_context.system_image
        else:
            # Seems older QEMU versions do not support the 'bios' parameter, so
            # we can't use
            #   qemu.bios = self.run_context.system_image
            # and have to stick to loading a kernel
            qemu.config['kernel'] = self.run_context.system_image

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
        assert(0 == len(qemu.config['serial_ports']))
        if not has_syslog_on_uart_1:
            # UART 0 is syslog
            qemu.sys_log_setup(
                self.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                0)

        if (has_data_uart):
            # UART 0 or UART 1 is used for data
            qemu.add_serial_port(f'tcp:localhost:{self.qemu_uart_network_port},server')
        elif has_syslog_on_uart_1:
            # UART 0 must be a dummy in this case
            assert(0 == len(qemu.serial_ports))
            qemu.add_serial_port('null')

        if has_syslog_on_uart_1:
            assert(1 == len(qemu.config['serial_ports']))
            # UART 1 is syslog
            qemu.sys_log_setup(
                self.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                1)

        if self.run_context.platform == 'sabre':
            # QEMU sabre uses tap2 for the native networking support (not using
            # the proxy)
            qemu.add_dev_nic_tap('tap2')

        elif qemu.get_machine() == 'virt':
            # Avoid an error message on the ARM virt platform that the
            # device "virtio-net-pci" init fails due to missing ROM file
            # "efi-virtio.rom".
            # ToDo: check virt platform of other architectures
            assert(qemu.config['cpu'].startswith('cortex-a'))
            qemu.add_dev_nic_none()

        # SD Card setup,
        if self.run_context.platform == 'zynqmp':
            # QEMU boots from a SD card, so the image must be set up. And there
            # are 2 QEMU instances actually, thus some more setup is needed.
            qemu.setup(
                os.path.join(
                    self.run_context.resource_dir,
                    'zcu102_sd_card'),
                self.run_context.log_dir)
        elif self.sd_card_size and (self.sd_card_size > 0):
            # SD card (might be ignored if target does not support this)
            machine = qemu.get_machine()
            if (machine in ['spike', 'sifive_u', 'mig-v', 'virt']):
                self.print(f'QEMU: ignoring SD card image, not supported for {machine}')
            else:
                sd_card_image = os.path.join(self.run_context.log_dir, 'sdcard1.img')
                # ToDo: maybe we should create a copy here and not
                #       modify the original file...
                with open(sd_card_image, 'wb') as f:
                    f.truncate(self.sd_card_size)
                qemu.add_sdcard_from_image(sd_card_image)

        # start QEMU
        qemu_proc = qemu.start(
                        log_file_stdout = self.get_log_file_fqn('qemu_out.txt'),
                        log_file_stderr = self.get_log_file_fqn('qemu_err.txt'),
                        additional_params = self.additional_params,
                        printer = self.get_printer(),
                        print_log = print_log)

        if not qemu_proc:
            raise Exception('could not start QEMU')
        self.process_qemu = qemu_proc

        if print_log:
            # now that a QEMU process exists, start the monitor thread. The
            # checker function ensures it automatically terminates when the
            # QEMU process terminates. We use an infinite timeout, as we don't
            # care when the system log file is created - it may take some time
            # if nothing is logged or it may not happen at all if nothing is
            # logged.
            self.system_log_file.start_monitor(
                printer = self.get_printer(),
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
            raise Exception(f'ERROR: missing proxy app: {proxy_app}')

        if (serial_qemu_connection != 'TCP'):
            raise Exception(
                f'ERROR: invalid Proxy/QEMU_connection mode: {serial_qemu_connectio}')

        # start the bridge between QEMU and the Proxy
        self.bridge.start_server(self.proxy_network_port)

        # start the proxy and have it connect to the bridge
        cmd_arr = [
            proxy_app,
            '-c', f'TCP:{self.proxy_network_port}',
            '-t', '1' # enable TAP
        ]

        self.process_proxy = process_tools.ProcessWrapper(
                                cmd_arr,
                                log_file_stdout = self.get_log_file_fqn('proxy_out.txt'),
                                log_file_stderr = self.get_log_file_fqn('proxy_err.txt'),
                                printer = self.get_printer(),
                                name = 'Proxy'
                             )

        self.print(f'starting Proxy: {" ".join(cmd_arr)}')
        self.print(f'  proxy stdout: {self.process_proxy.log_file_stdout}')
        self.print(f'  proxy stderr: {self.process_proxy.log_file_stderr}')

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
