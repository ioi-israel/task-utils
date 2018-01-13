"""
General template for a task module, containing all possible parameters
with documentation.
"""

import random


def get_task_params():
    """
    Return a dictionary specifying all task parameters.
    Testcase generation is done in a separate function.
    """

    return {
        # Task types: "Batch"/"OutputOnly"/"TwoSteps"
        "type": "Batch",

        # Limits. Time is in seconds, memory is in MB.
        # Fractions are allowed for time.
        "time": 3,
        "memory": 64,

        # Checker. A program that checks the contestant's output.
        # This is needed when there is more than one correct output,
        # so a simple diff against the correct output is not appropriate.
        #
        # A checker must be a C++ file. It receives 3 file paths as arguments:
        # input, output, contestant output. It must print a number between
        # 0 and 1 to stdout, where 1 is full success. It can print to stderr
        # a message that will be visible to the contestant.
        #
        # Compilation: g++ -Wall -O2 -std=c++0x checker.cpp
        "checker": "checker.cpp",

        # Graders. A grader is a file that is compiled with the contestant's
        # file. It normally contains a main function, so the contestant only
        # implements a function.
        #
        # There should be one grader per programming language.
        "graders": ["graders/grader.cpp"],

        # Headers. A header is a .h file that contains declarations.
        # This is useful when working with graders.
        "headers": ["task.h"],

        # Managers. Used for TwoSteps tasks. It is compiled with the
        # contestant's file. There should be a manager for every language.
        "managers": ["manager.cpp"],

        # Statements. Each one is a PDF in some language, viewable to the
        # contestant in the "Statement" page. Currently the allowed language
        # codes are "he" and "en".
        "statements": [
            {
                "language": "he",
                "path": "statement.pdf"
            }
        ],

        # Attachments for contestants.
        # Text files newlines should be converted from LF to CRLF,
        # to support Windows environment.
        "attachments": ["attachment.zip"],

        # Generator: file to use for generating output files.
        # Used only if the generate_testcase function below does not
        # produce an "output" key in the returned dictionary.
        #
        # This is useful when Python is too slow,
        # or coding the solution in Python is undesirable.
        #
        # Compilation: g++ -Wall -O2 -std=c++0x prog.cpp
        "output_generator": "prog.cpp",

        # Option to read testcases from the task directory instead of
        # generating them. In this case, each subtask (below) needs to
        # specify a "num_testcases" field.
        #
        # The files will be searched for in the given format.
        # The functions receive:
        # - si: the 0-based index of the subtask.
        # - sti: the 0-based index of the testcase in the subtask.
        # - tti: the 0-based index of the total testcases.
        "existing_testcases_format": {
            "input": lambda si, sti, tti: "testcases/%d.in" % (tti + 1),
            "output": lambda si, sti, tti: "testcases/%d.out" % (tti + 1),
        },

        # List of subtasks. Each has a score and a list of testcases.
        # Each testcase is a dictionary of parameters (seed, N, etc.)
        # To generate a testcase, the function generate_testcase will
        # be called with the same parameters, i.e.:
        # generate_testcase(**testcase_dictionary)
        #
        # If dealing with existing testcases, each subtask must provide a
        # "num_testcases" field instead of "testcases".
        "subtasks": [
            {"score": 10, "testcases": [
                {"seed": 123, "n": 2},
                {"seed": 456, "n": 2}
            ]},
            {"score": 90, "testcases": [
                {"seed": 432, "n": 10},
                {"seed": 431, "n": 10}
            ]}
        ]
    }


def generate_testcase(seed, n):
    """
    Generate a testcase according to the testcase parameters.
    Return a dictionary with an "input" field, and an optional
    "output" field. If "output" is omitted, then an "output_generator"
    must be present in the task parameters, and it will be used
    to produce an output.

    If the task does not need output files, put an empty string
    in the "output" field.
    """

    random.seed(seed)
    arr = [random.randint(1, 100) for _ in xrange(n)]
    answer = sum(arr)

    # Before finishing, do sanity checks.
    # For example, make sure the answer fits in an int.
    assert 0 <= min(arr) <= max(arr) <= 2 ** 30
    assert 0 <= answer <= 2 ** 30

    return {
        "input": str(n) + "\n" + "\n".join(map(str, arr)),
        "output": str(answer)
    }
