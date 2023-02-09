"""
Logs parser

This module allows the user to parse a log searching in it in a way that is
useful for testing. Such operations like looking for a regex match are
performed "online" on the log until the match condition happens or a timeout
occurred
"""

import board_automation


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

    text = ''
    line_reader = board_automation.line_reader.Stream_Line_Reader(f, timeout_sec)
    # We can't simply use line_reader.find_matches_in_lines() because we also
    # have to capture the text. However, it seems most callers don't really care
    # about the text, so this is just wasting resources. The whole function
    # should get deprecated and the caller should use the Stream_Line_Reader
    # directly. And capture the text if this is really needed.
    for line in line_reader:
        text += line
        mo = regex.search(line)
        if mo:
            return (text, mo.group(0))

    return (text, None)


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

    text = ''
    line_reader = board_automation.line_reader.Stream_Line_Reader(f, timeout_sec)
    # We can't simply use line_reader.find_matches_in_lines() because we also
    # have to capture the text. However, it seems most callers don't really care
    # about the text, so this is just wasting resources. The whole function
    # should get deprecated and the caller should use the Stream_Line_Reader
    # directly. Or do this and capture the text if this is really needed.
    for expr in expr_array:
        for line in line_reader:
            text += line
            if expr in line:
                break;
        else: # no break, all lines processed
            print(f'No match for: {expr}')
            return (False, text, expr)

    # If we arrive here, all strings were found
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

    text = ''
    line_reader = board_automation.line_reader.Stream_Line_Reader(f)
    for idx_seq, (expr_array, timeout_sec) in enumerate(seq_expr_array):
        line_reader.set_timeout(timeout_sec)
        for expr in expr_array:
            for line in line_reader:
                text += line
                if expr in line:
                    break;
            else: # no break, all lines processed
                print(f'No match in sequence #{idx} for: {expr}')
                return (False, text, expr, idx)

    # If we arrive here, all strings were found.
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

    text = ''
    line_reader = board_automation.line_reader.Stream_Line_Reader(f, timeout_sec)
    # Make a copy of the list, where we will remove the items we find.
    arr_remaining = expr_array[:]
    for line in line_reader:
        text += line
        # We can't delete elements from the list we are looping over, so do
        # the looping over a copy. This is acceptable, because we expect
        # the list of expressions to search for to be quite small.
        arr_copy = arr_remaining[:]
        for idx, obj in enumerate(arr_copy):
            if isinstance(obj, str):
                if obj in line:
                    break
            else:
                mo = obj.search(line)
                if mo:
                    break
        else: # no break, because no item matched
            continue
        # If we arrive here, there was a match. We are done if there are no
        # more itemt to matchitemts left.
        arr_remaining.pop(idx)
        if not arr_remaining:
            return (True, text, None)
    # If we arrive here, we could not find all strings from the set.
    return (False, text, arr_remaining)
