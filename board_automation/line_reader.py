#!/usr/bin/python3

import os
import fcntl
import dataclasses
from . import tools


#===============================================================================
#===============================================================================
# This is an iterator over line in the stream. It's intended to be used on a
# non-blocking stream, because then we can honor the timeout nicely - with
# respect to the granularity of the sleep_timeout.
# If the stream is blocking, the timeout will not work as expected, because we
# can't unblock the underlying stream.readline() that is used.
#
# Basically, this gives us a "stream.readline(timeout)", that does not exist in
# Python. There is a patch proposal in https://bugs.python.org/issue23236 that
# seem to do something similar. Also, the asyncio module might offer such a
# features, but that still something to be explored.
class Stream_Line_Reader():

    #---------------------------------------------------------------------------
    # The default 'None' as timeout indicates an infinite timeout. Using 100 ms
    # as sleep timeout seems a good trade-off for logs, especially when they
    # come from a 115200 baud UART connection. We don't want to block for too
    # long, but also do not cause CPU load by just busy waiting for data.
    def __init__(self, stream, timeout = None, sleep_timeout = 0.1,
                 checker_func = None):
        self.stream = stream # this can be None is the stream is not ready yet
        self.sleep_timeout = sleep_timeout
        self.checker_func = checker_func
        self.reset_iterator()
        self.set_timeout(timeout)


    #---------------------------------------------------------------------------
    # Passing None for the timeout will create an infinite timeout.
    def set_timeout(self, timeout):
        self.timeout = tools.Timeout_Checker(timeout)


    #---------------------------------------------------------------------------
    def reset_iterator(self):
        # We are a line iterator and comply with Python rule, that once an
        # iterator's __next__() method raises StopIteration, it must continue to
        # do so on subsequent calls. Implementations that do not obey this
        # property are deemed broken. However, there are cases where the caller
        # has reached the end of the log and then continue.
        self.stopIteration = False


    #---------------------------------------------------------------------------
    def open_stream(self):
        # sub-classes can overwrite this to implement lazy opening for streams,
        # e.g. for file.
        return self.stream

    #---------------------------------------------------------------------------
    # Returns True if waiting worked. Or False if waiting was no possible or
    # was canceled.
    def wait(self):

        # We can't wait if the timeout is not set or has expired.
        if (self.timeout is None) or self.timeout.has_expired():
            return False

        self.timeout.sleep(self.sleep_timeout)

        # Check for custom abort after sleeping, as there could have been an
        # asynchronous cancellation.
        if self.checker_func and not self.checker_func():
            return False

        return True


    #---------------------------------------------------------------------------
    def readline(self):
        line = ''
        while True:
            stream = self.open_stream()
            if stream is not None:
                line += stream.readline()
                # If universal newline handling is specified when opening a file
                # or stream, readline() returns a string terminated by '\n' for
                # every complete line. Any '\r', '\n' or '\r\n' is considered a
                # line break.
                # If the last line of a file doesn't end in a line break, the
                # string returned by readline() will not end with a '\n'. This
                # makes the returned string unambiguous, and any data that is
                # appended to the file or stream is read properly. Repeated
                # calls to readline() may return multiple strings without '\n',
                # each containing the new data written:
                #
                #  loop iteration 1:   | line part |...
                #  loop iteration 2:               | line part |...
                #  ...
                #  loop iteration k:                           | line+\n |
                #
                # There is a line break bug in some logs, where '\n\r' is used
                # instead of '\r\n'. This is interpreted as two line breaks,
                # thus we see an emty line.
                if line.endswith('\n'):
                    # We do not check the timeout if we have a complete line, it
                    # is checked only for incomplete lines or if this function
                    # would block. Rationale is, that we assume we can read data
                    # faster than it can be produced. Thus we will see an
                    # incomplete line or block eventually anyway. Also, complete
                    # lines with potentially useful data are more important for
                    # the caller than the timeouts for a few ms of timeout
                    # jitter.
                    return line

            # If we arrive here, we could not read a complete line. If there is
            # time left, then continue waiting for data. If there was a timeout
            # or abort, then return what we have. It could be an empty string
            # if there was no new data.
            if not self.wait():
                return line


    #---------------------------------------------------------------------------
    def flush(self):
        # Read all data from the raw stream.
        stream = self.open_stream()
        if stream is not None:
            while stream.readline():
                pass
        self.reset_iterator()


    #---------------------------------------------------------------------------
    def __iter__(self):
        return self


    #---------------------------------------------------------------------------
    # returns:
    # - a string terminated by line break for complete lines
    # - a string without line break if it's the last incomplete line
    # or raises a StopIteration exception on timeout
    def __next__(self):

        # Comply with Python rule, that once an iterator's __next__() method
        # raises StopIteration, it must continue to do so on subsequent calls.
        # Implementations that do not obey this property are deemed broken.
        if self.stopIteration:
            raise StopIteration()

        # Read a line. This can return
        # - None to indicate there was a general stream problem. Derived classes
        #   may use this.
        # - A string not terminated by '\n' to indicate a the end of the stream
        #   has been reached and the timeout happened. Or there was a forced
        #   abort.
        #   empty string is no data has been read at all
        # - A string terminated by '\n' to indicate a complete line has been
        #   read
        # This may also raise an exception on fatal errors.
        line = self.readline()

        if (line is None) or (line == ''):
            # 'None' indicates a problem with the stream, an empty string
            # indicates a timeout (or abort) with no new data in the steam. As
            # an iterator, there is no point returning no data, so we can stop
            # immediately.
            self.stopIteration = True
            raise StopIteration()

        if not line.endswith('\n'):
            # We cold only read a line fragment, before the timeout or an abort
            # happened. Mark the iterator as stopped, the next iteration will
            # report the stop then.
            self.stopIteration = True

        # return the line or line fragment
        assert len(line) > 0
        return line


    #---------------------------------------------------------------------------
    # obj can be a
    # - primitive type
    #   - plain string
    #   - compiled regex
    # - a (ordered) list of primitive types to match in the given order
    # - a (unordered) set of primitive types to match in any order
    # - tuple (obj, timeout_sec), where obj can be a primitive type or a
    #    a list/set of primitive types.
    # - list of tupels, where each tuple can contain a list or set of primitive
    #    types
    def find_matches_in_lines(self, obj):

        @dataclasses.dataclass
        class Ctx:
            ok: bool = False

        @dataclasses.dataclass
        class CtxList(Ctx):
            items: list = None # dataclasses.field(default_factory=list)
            def get_missing(self):
                if self.ok: return None
                e = items[-1]
                if isinstance(e, CtxItemMissing): return e.missing
                return e.get_missing()

        @dataclasses.dataclass
        class CtxItemMatch(Ctx):
            match: str = None
            line_offset: int = None

        @dataclasses.dataclass
        class CtxItemMissing(Ctx):
            missing: str = None
            def get_missing(self):
                return None if self.ok else self.missing

        # For a tuple it must be (obj, timeout_sec).
        if isinstance(obj, tuple):
            assert len(obj) == 2
            (sub_obj, timeout_sec) = obj
            self.set_timeout(timeout_sec)
            obj = sub_obj

        # For a list we just call us recursively for each element. That allows
        # even having lists of tupels of lists ...
        if isinstance(obj, list):
            items = []
            for idx, obj in enumerate(obj):
                ret = self.find_matches_in_lines(obj)
                items.append(ret)
                if not ret.ok:
                    return CtxList(ok=False, items=items)
            # If we arrive here, we are done with the list and all items were
            # found.
            return CtxList(ok=True, items=items)

        # For a set, the order of the items does not matter, but all elements
        # must match eventually.
        if isinstance(obj, set):
            items = []
            # Make a copy of the set as list, in the copy we will remove the
            # items we have found. Removing by index works in lists only, but
            # not in sets
            obj_remaining = list(obj)
            for idx, line in enumerate(self):
                # Iterate over the set to check if we have a match. We can't
                # delete elements from the what we are looping over, so we need
                # another copy for the looping. This is acceptable, because we
                # expect the number of expressions to search for to be quite
                # small.
                regex_match = None
                for pos, obj in enumerate(obj_remaining):
                    if isinstance(obj, str):
                        if obj in line:
                            break
                    else:
                        mo = obj.search(line)
                        if mo:
                            regex_match = mo.group(0)
                            break
                else: # no break, nothing in the set matched
                    continue
                # We have found a match. If this was the last one remaining in
                # the set then we are done.
                items.append( CtxItemMatch(ok=True, line_offset=idx,
                                           match=regex_match) )

                obj_remaining.pop(pos)
                if not obj_remaining:
                    return CtxList(ok=True, items=items)
            # If we arrive here, we could not find all strings from the set.
            return CtxItemMissing(ok=False, missing=list(obj_remaining))

        # If we are here, it must be a string or a compiled regex. We only check
        # for the string type explicitly, anything else passed here must just
        # behave like a compiled regex, we don't care exactly what it is.

        is_str = isinstance(obj, str)
        for idx, line in enumerate(self):
            # Note that idx is relative to the current enumerator. It is not the
            # absolute line number within the whole (file-)stream, because we
            # can be called multiple times on the same stream, where it is not
            # reset.
            if is_str:
                if obj in line:
                    return CtxItemMatch(ok=True, line_offset=idx)
            else:
                mo = obj.search(line)
                if mo:
                    # Return the matched item also, so caller know what exactly
                    # the regex matched.
                    return CtxItemMatch(ok=True, line_offset=idx,
                                        match=mo.group(0))

        # If we arrive here, there was a timeout before we found a match.
        return CtxItemMissing(ok=False, missing=obj)


#===============================================================================
#===============================================================================

class File_Line_Reader(Stream_Line_Reader):

    #---------------------------------------------------------------------------
    # Sleeping 100 ms seems a good trade-off between not stalling unnecessarily
    # and causing too much CPU load looping around.
    def __init__(self, fileName, timeout = None, sleep_timeout = 0.1,
                 checker_func = None, newline = None, mode = 'rt',
                 encoding = 'latin-1'):

        super().__init__(None, timeout, sleep_timeout, checker_func)
        self.fileName = fileName
        self.newline = newline
        self.mode = mode
        self.encoding = encoding


    #---------------------------------------------------------------------------
    # Overwrite the parent's function to open the file stream in non-blocking
    # mode.
    def open_stream(self):

        if self.stream is None:
            # We can't provide a stream if the file does not exist (yet).
            if not os.path.isfile(self.fileName):
                return None
            # Open the file for reading in on-blocking mode. This returns a
            # handle or raises an exception on error
            f = open(self.fileName, newline = self.newline,
                     mode = self.mode, encoding = self.encoding)
            assert f is not None
            fd = f.fileno()
            flag = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
            self.stream = f

        return self.stream
