#!/usr/bin/python3

import sys
import traceback
import os
import pathlib
import fcntl
import socket
import selectors
import threading
import time
import datetime
import re
import subprocess


#-------------------------------------------------------------------------------
# implement "@class_or_instancemethod" attribute for methods
class class_or_instance_method(classmethod):

    def __get__(self, instance, type_):

        descr_get = super().__get__ if instance is None \
                    else self.__func__.__get__

        return descr_get(instance, type_)


#-------------------------------------------------------------------------------
def add_subdir_to_sys_path(path, subdir):
    sys.path.append(
        os.path.join(
            str(pathlib.Path(path).parent.absolute()),
            subdir
        )
    )


#-------------------------------------------------------------------------------
def print_files_from_folder(folder):

    filenames = os.listdir(folder)

    for f in filenames:
        fqn = os.path.join(folder, f)
        stat_info = os.lstat(fqn)
        time_str = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.gmtime(stat_info.st_mtime))

        print('  {:8d}   {}   {}'.format(stat_info.st_size, time_str, f))


#-------------------------------------------------------------------------------
def get_mountpoints():

    def parse_mntpt(line):
        dev, mntpt, _ = line.split(None, 2)
        return dev, mntpt

    with open('/proc/mounts') as f:
        return dict(map(parse_mntpt, f.readlines()))


#-------------------------------------------------------------------------------
def get_mountpoint_for_dev(dev):

    mntpts = get_mountpoints()
    return mntpts.get(dev)


#-------------------------------------------------------------------------------
def get_disk_id_for_dev(dev):
    folder = '/dev/disk/by-id'

    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def get_disk_path_for_dev(dev):

    # for dev, mp in mntpts.items(): print('{} -> {}'.format(dev, mp))

    folder = '/dev/disk/by-path'
    # contains things like
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0-part1 -> ../../sda1
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0 -> ../../sda
    #
    # check for pattern: <buf>-usb-<path>-scsi-<path>[-<id>]


    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def find_usb_by_serial(serial):

    base_dir = '/sys/bus/usb/devices'

    print('check {} for serial: {}'.format(base_dir, serial))

    def get_id(dn, id_file):
        file_name = os.path.join(dn, id_file)
        if not os.path.exists(file_name): return None
        with open(file_name) as f:
            return f.read().strip()

    for usbid in os.listdir(base_dir):
        dn = os.path.join(base_dir, usbid)
        if (serial == get_id(dn, 'serial')):
            print('  {}:{} at {}'.format(
                    get_id(dn, 'idVendor'),
                    get_id(dn, 'idProduct'),
                    dn))
            # no break here, serial may not be unique


#-------------------------------------------------------------------------------
def create_sd_img(sd_img_path, sd_img_size, sd_content_list = []):
    # Create SD image file
    #   - Create a binary file and truncate to the received size.
    with open(sd_img_path, "wb") as sd_image_file:
        sd_image_file.truncate(sd_img_size)

    # Format SD to a FAT32 FS
    subprocess.check_call(['mkfs.fat', '-F 32', sd_img_path])

    # Copy items to SD image:
    #   - sd_content_list is a list of tuples: (HOST_OS_FILE_PATH, SD_FILE_PATH).
    #   - mcopy (part of the mtools package) copies the file from the linux host
    #     to the SD card image without having to mount the SD card first.
    for item in sd_content_list:
        subprocess.check_call([
            'mcopy',
            '-i',
            sd_img_path,
            item[0],
            os.path.join('::/', item[1])])


#-------------------------------------------------------------------------------
# this is just a convenience function wrapping threading.Thread that can be
# used to run a function in a thread. It's use as
#
#   import tools
#   ...
#   def some_method(self, params):
#      ...
#      def my_thread(thread):
#          self.do_something_special(params)
#
#      self.thread = tools.run_in_thread(my_thread)
#
# instead of doing
#
#   import threading
#   ...
#   def some_method(self, params):
#      ...
#      def my_thread():
#          self.do_something_special(params)
#
#
#      self.thread = threading.Thread(target = my_thread)
#      self.thread.start()
#

#===============================================================================
#===============================================================================
class MyThread(threading.Thread):

    #---------------------------------------------------------------------------
    def __init__(self, func, daemon=None):
        super().__init__(daemon=daemon)
        self.func = func


    #---------------------------------------------------------------------------
    def __str__(self):
        return '{}/{}()'.format(self.name, self.func.__name__)


    #---------------------------------------------------------------------------
    def run(self):
        try:
            self.func(self)
        except: # catch really *all* exceptions
            (e_type, e_value, e_tb) = sys.exc_info()
            print('EXCEPTION in thread {}: {}{}'.format(
                self,
                ''.join(traceback.format_exception_only(e_type, e_value)),
                ''.join(traceback.format_tb(e_tb))))


#-------------------------------------------------------------------------------
def run_in_thread(func):
    t = MyThread(func)
    t.start()
    return t

#-------------------------------------------------------------------------------
def run_in_daemon_thread(func):
    t = MyThread(func, daemon=True)
    t.start()
    return t


#===============================================================================
#===============================================================================

class PrintSerializer():

    #---------------------------------------------------------------------------
    def __init__(self):
        self.lock = threading.Lock()


    #---------------------------------------------------------------------------
    def print(self, msg):

        with self.lock:
            # msg = '[{}] {}'.format(
            #         msg,
            #         datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
            print(msg)


#===============================================================================
#===============================================================================

class Timeout_Checker(object):

    #---------------------------------------------------------------------------
    # any value less than 0 or None means infinite, the value 0 indicates a zero
    # timeout, ie. "do not block".
    def __init__(self, timeout_sec):

        self.time_end = \
            timeout_sec.time_end if isinstance(timeout_sec, Timeout_Checker) \
            else None if (timeout_sec is None) or (timeout_sec < 0) \
            else time.time() + timeout_sec


    #---------------------------------------------------------------------------
    @classmethod
    def infinite(cls):
        return cls(-1)


    #---------------------------------------------------------------------------
    def is_infinite(self):
        return (self.time_end is None)


    #---------------------------------------------------------------------------
    # Returns a value greater zero if time left, zero if the timeout has been
    # reached or a negative value if the timeout is infinite.
    def get_remaining(self):

        if self.is_infinite():
            return -1

        time_now = time.time()
        return (self.time_end - time_now) if (self.time_end > time_now) else 0


    #---------------------------------------------------------------------------
    def has_expired(self):
        v = self.get_remaining()
        assert( (v == -1 and self.is_infinite()) or (v >= 0))
        return (0 == v)


    #---------------------------------------------------------------------------
    # Returns a Timeout_Checker instance covering up to the given number of
    # seconds, where timeout_sec can be a value or another Timeout_Checker
    # instance. Any value passed for timeout_sec that is less than 0 or None
    # means infinite. The timeout cannot exceed the amount of time left in
    # parent's timeout, but it can be infinite if the parent's timeout is
    # infinite.
    def sub_timeout(self, timeout_sec):

        sub_timeout = Timeout_Checker(timeout_sec)

        # If we are an infinite timeout, we can can grant anything, otherwise
        # we must cut the timeout at out own timeout and basically return a
        # clone of us.
        if not self.is_infinite() \
           and (sub_timeout.is_infinite() \
                or (sub_timeout.get_remaining() > self.get_remaining())):
            return Timeout_Checker(self)

        return sub_timeout


    #---------------------------------------------------------------------------
    # Sleep either for the given time, if this is less than the remaining time
    # in our timeout. Otherwise sleep for the remaining time in our timeout
    # only. The parameter timeout can hold a value of another Timeout_Checker
    # instance.
    def sleep(self, timeout):

        # We don't handle None as 0, because if we see None here this is likely
        # a bug in the caller's code.
        if (timeout is None):
            raise Exception('can''t sleep() for timeout "None"')

        # Passing negative values is likely a bug in the caller's code.
        if not isinstance(timeout, Timeout_Checker) and (timeout < 0):
            raise Exception('can''t sleep() for negative timeouts')

        sub_timeout = self.sub_timeout(timeout)

        # Waiting an infinite time when we have an infinite timeout is not
        # supported, because this is likely a bug in the caller's code.
        if sub_timeout.is_infinite():
            assert(self.is_infinite())
            raise Exception('can''t sleep() for an infinite time')

        # get the timeout, sleep only if it has not already expired
        timeout = sub_timeout.get_remaining()
        if (0 != timeout):
            time.sleep(timeout)


#===============================================================================
#===============================================================================

class Log_File(object):

    #---------------------------------------------------------------------------
    def __init__(self, name):
        self.name = name
        self.monitor_thread = None


    #---------------------------------------------------------------------------
    # if the file does not exist, keep checking every 100 ms until the timeout
    # has expired or the checker function says we can stop
    def open_non_blocking(
            self,
            timeout = None,
            newline = None, # use universal newline mode by default
            mode = 'rt', # read-only text file
            checker_func = None ):

        while True:

            if os.path.isfile(self.name):
                f = open(self.name, mode, newline=newline)
                if f:
                    fd = f.fileno()
                    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

                return f

            if not timeout or timeout.has_expired():
                return None

            if checker_func and not checker_func():
                return None

            # wait and try again. Using 100 ms seems a good trade-off here, so
            # we don't block for too long or cause much CPU load
            timeout.sleep(0.1)


    #---------------------------------------------------------------------------
    def start_monitor(
            self,
            printer,
            timeout = None,
            checker_func = None):

        #-----------------------------------------------------------------------
        def monitoring_thread(thread):
            # time starts ticking now, since the system is running. The file
            # may not be created until any data is written into it, so
            # successfully opening it can take a while.
            start = datetime.datetime.now()
            f_log = self.open_non_blocking(
                        timeout = timeout,
                        checker_func = checker_func)
            if not f_log:
                # we see this when opening the file failed and we've finally
                # reached the timeout or the checker function told us to stop
                raise Exception('monitor failed, could not open: {}'.format(self.name))

            with f_log:
                is_abort = False
                while not is_abort:
                    line = ''
                    while True:
                        # readline() returns a string terminated by "\n" for
                        # every complete line. On timeout (ie. EOF reached),
                        # there is no terminating "\n".
                        line += f_log.readline()
                        if line.endswith('\n'):
                            # Unfortunately, there is a line break bug in some
                            # logs, where "\n\r" (LF+CR) is used instead of
                            # "\r\n" (CR+LF). Universal newline handling only
                            # considers "\r", "\n" and "\r\n" as line break,
                            # thus "\n\r" is taken as two line breaks and we
                            # see a lot of empty lines in the logs
                            break

                        # could not read a complete line, check termination
                        # request
                        if checker_func and not checker_func():
                            is_abort = True
                            break

                        # wait and try again. Using 100 ms seems a good
                        # trade-off here, so we don't block for too long or
                        # cause too much CPU load
                        time.sleep(0.1)

                    if (len(line) > 0):
                        printer.print('[{}] {}'.format(
                            datetime.datetime.now() - start,
                            line.strip()))

            # printer.print('[{}] monitor terminated for {}'.format(self, self.name))


        self.monitor_thread = run_in_thread(monitoring_thread)

    #---------------------------------------------------------------------------
    @classmethod
    def do_find_match_in_lines(cls, hLog, regex, timeout = None):

        regex_compiled = re.compile( regex )
        line = ''

        while True:

            # if we've opened the file in non-blocking mode, this is a
            # non-blocking read, ie if we read something not ending with '\n',
            # it means we have reached the end of input
            line += hLog.readline()
            is_timeout = (timeout is None) or timeout.has_expired()
            if (not line.endswith('\n')) and (not is_timeout):
                # sleep 100 ms or what is left from the timeout. We can use any
                # value here, 100 ms seem a good trade-off between blocking and
                # just wasting CPU time.
                timeout.sleep(0.1)

            else:
                mo = regex_compiled.search(line)
                if mo:
                    return mo.group(0)

                if is_timeout:
                    return None

                line = ''


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_sequence(cls, hLog, str_arr, timeout = None):
        for idx, expr in enumerate(str_arr):
            regex = re.escape(expr)
            match = cls.do_find_match_in_lines(hLog, regex, timeout)
            if match is None:
                return (False, idx)

            # we don't support any wildcards for now
            assert(match == expr)

        # done with the sequence, all strings found
        return (True, None)


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_multiple_sequences(cls, hLog, seq_arr, timeout = None):
        for idx, (str_arr, timeout_sec) in enumerate(seq_arr):
            # we already have the first timeout running, for for every
            # further element we set up a new timeout
            if (idx > 0):
                timeout = Timeout_Checker(timeout_sec)

            (ret, idx2) = cls.do_match_sequence(hLog, str_arr, timeout)
            if not ret:
                return (False, idx, idx2)

        # done with the array of sequences
        return (True, None, None)


    #---------------------------------------------------------------------------
    def find_match_in_lines(self, regex, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_find_match_in_lines(hLog, regex, timeout)


    #---------------------------------------------------------------------------
    def match_sequence(self, str_arr, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_sequence(hLog, str_arr, timeout)


    #---------------------------------------------------------------------------
    def match_multiple_sequences(self, seq_arr):

        # opening the file counts towards the first sequences timeout
        (expr_array, timeout_sec) = seq_arr[0]
        timeout = Timeout_Checker(timeout_sec)

        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_multiple_sequences(hLog, seq_arr, timeout)
