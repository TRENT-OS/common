"""
Logs parser

This module allows the user to parse a log searching in it in a way that is
useful for testing. Such operations like looking for a regex match are
performed "online" on the log until the match condition happens or a timeout
occurred
"""

import re
from board_automation import tools


#------------------------------------------------------------------------------
def open_file_non_blocking(file_name, mode='rt', newline=None,
                           encoding='latin-1'):
    """
    Opens a file and set non blocking OS flag. By default, the file is opened as
    'text file' in 'read-only' mode and universal newline detection is applies.
    Encoding default to 'latin-1' instead the python's 'utf-8' default to stick
    to single-byte chars and avoid encoding exceptions in case corrupted data is
    read.
    Returns a file object.
    """

    return tools.Log_File(file_name).open_non_blocking(
                mode = mode,
                newline = newline,
                encoding = encoding)


#------------------------------------------------------------------------------
def read_line_from_log_file_with_timeout(f, timeout_sec=None):
    """
    Read a line from a logfile with a timeout. If the timeout is None, it is
    disabled. The file handle must be opened in non-blocking mode.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.
    """

    timeout = tools.Timeout_Checker(timeout_sec)
    line = ""

    while True:
        # readline() will return a string, which is terminated by "\n" for
        # every line. For the last line of the file, it returns a string
        # that is not terminated by "\n" to indicate the end of the file. If
        # another task is appending data to the file, repeated calls to
        # readline() may return multiple strings without "\n", each containing
        # the new data written to the file.
        #
        #  loop iteration 1:     | line part |...
        #  loop iteration 2:               | line part |...
        #  ...
        #  loop iteration k:                                | line+\n |
        #
        # There is a line break bug in some logs, "\n\r" is used instead of
        # "\r\n". Universal newline handling accepts "\r", "\n" and "\r\n" as
        # line break. We end up with some empty lines then as "\n\r" is taken
        # as two line breaks.
        data = f.readline()
        line += data
        if line.endswith("\n"):
            return line

        is_fragment = (len(line) > 0)

        if timeout.has_expired():
            # Fake a newline character if there was data.
            return (line + "\n") if is_fragment else None

        # Sleep and check again. This will sleep less than the requested time
        # if the timeout has not enough time left. If there was at least some
        # data, we might have been unlucky and just read while a line is about
        # to be appended. Wait just 100ms in this case, otherwise wait 500ms
        # because it seems we are really blocked waiting on new data to arrive.
        timeout.sleep(0.1 if is_fragment else 0.5)


#------------------------------------------------------------------------------
def get_match_in_line(f, regex, timeout_sec=None):
    """
    Gets the first regex match in a text file parsing it line by line.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    regex(Pattern): a compiled regular expression to look for
    timeout_sec(optional): timeout in seconds, None means disabled

    Returns:
    text(str): the text from the begin of the search until the first match or the end
    match(str): the matching string
    """

    timeout = tools.Timeout_Checker(timeout_sec)
    regex_compiled = re.compile( regex )
    text = ""

    while True:
        line = read_line_from_log_file_with_timeout(f, timeout)
        if line is None:
            return (text, None)

        text += line
        mo = regex_compiled.search(line)
        if mo:
            return (text, mo.group(0))


#-------------------------------------------------------------------------------
def check_log_match_sequence(f, expr_array, timeout_sec=None):
    """
    Takes an array of regular expressions and perform the simple test. The
    order of the elements in the array matters, must be the same order in the
    log file.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    expr_array: array with strings to match
    timeout_sec(optional): timeout in seconds, None means disabled
    """

    timeout = tools.Timeout_Checker(timeout_sec)
    text = ""

    for expr in expr_array:
        (text_part, match) = get_match_in_line(f, re.escape(expr), timeout)
        text += text_part
        if match is None:
            print("No match for '%s'" % expr)
            return (False, text, expr)

        # We don't support any wildcards for now.
        assert(match == expr)

    return (True, text, None)


#-------------------------------------------------------------------------------
def check_log_match_multiple_sequences(f, seq_expr_array):
    """
    Takes an array of tupels, each holding a timeout and sequence of regular
    expressions to match withing this timeout in the given order. Calls
    check_log_match_sequence() for each tupel.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    seq_expr_array: array of arrays with strings to match and timeout
    """

    text = ""

    for idx, (expr_array, timeout_sec) in enumerate(seq_expr_array):

        timeout = tools.Timeout_Checker(timeout_sec)

        for expr in expr_array:

            (text_part, match) = get_match_in_line(
                                    f,
                                    re.escape(expr),
                                    timeout)
            text += text_part
            if match is None:
                print('No match in sequence #{} for: {}'.format(idx, expr))
                return (False, text, expr, idx)

            # We don't support any wildcards for now.
            assert(match == expr)

    return (True, text, None, 0)


#-------------------------------------------------------------------------------
def check_log_match_set(f, expr_array, timeout_sec=None):
    """
    Take an array of regular expressions and perform the simple test. The order
    of the elements in the array does not matter, the matches just have to be
    there in the log occurring at any time at the least once per single
    expression.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    expr_array: array with strings to match
    timeout_sec(optional): timeout in seconds, None means disabled
    """

    timeout = tools.Timeout_Checker(timeout_sec)

    expr_dict = {}
    for expr in expr_array:
        expr_dict[expr] = re.compile( re.escape(expr) )

    text = ""

    while True:
        line = read_line_from_log_file_with_timeout(f, timeout)
        if line is None:
            return (False, text, expr_dict.keys())

        text += line

        # We can't modify the dictionary while iterating over it, thus we
        # create a list of items to remove.
        remove_expr = [];
        for expr in expr_dict:
            regex_compiled = expr_dict[expr]
            mo = regex_compiled.search(line)
            if not mo:
                continue

            match = mo.group(0)
            assert(match == expr) # We don't support any wildcards for now.
            remove_expr.append(expr)

        # Remove expression we have found.
        if remove_expr:
            for expr in remove_expr:
                expr_dict.pop(expr)

            if not expr_dict:
                return (True, text, None)


#-------------------------------------------------------------------------------
def find_assert(f):
    """
    Check if current output already contains an assert failure of any type.
    Start at the beginning and ensure that we set the file cursor back.
    """

    assert_re = re.compile(r'Assertion failed: @(.*)\((.*)\): (.*)\n')
    ret = None

    # check the whole log received so far
    f.seek(0)

    read_next_line = True

    while read_next_line:

        line = f.readline()
        # Lines end with a newline character (\n) unless it's the last line
        # and the file doesn't end with a newline. This makes the return value
        # unambiguous, if line is an empty string, the end of the file has been
        # reached, any blank lines are represented by string containing only a
        # single newline char.
        if not line.endswith("\n"):
            read_next_line = False
            line += "\n" # assert_re still expects a newline char

        mo = assert_re.search(line)
        if mo:
            ret = mo.group(0)
            read_next_line = False


    f.seek(0)

    # return match on None
    return ret

#-------------------------------------------------------------------------------
def check_result_or_assert(f, test_fn, test_args, timeout_sec=None):
    """
    Wait for a test result string or an assert specific to a test function
    appears in the output file.
    Any timeout applies only when the function would block after all available
    log data has been processed. As long as log data is available, it gets
    processed, even if the timeout has actually expired already. Rationale is,
    that it is assumed log data can be processed faster than it gets produced.
    The purpose of this timeout is not to be a global timeout for the test
    run, but just a limit how long to wait for new data.
    """

    timeout = tools.Timeout_Checker(timeout_sec)

    test_name = test_fn if test_args is None \
                else "%s(%s)" % (test_fn, test_args)

    assert_re = re.compile(r'Assertion failed: @%s: (.*)\n' % re.escape(test_name))
    result_re = re.compile(r'!!! %s: OK\n' % re.escape(test_name))

    while True:
        line = read_line_from_log_file_with_timeout(f, timeout)
        if line is None:
            return (False, None)

        mo = result_re.search(line)
        if mo is not None:
            return (True, None)

        mo = assert_re.search(line)
        if mo is not None:
            return (False, mo.group(1))
