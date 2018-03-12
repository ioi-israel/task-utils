#!/usr/bin/env python2

"""
A TaskProcessor is in charge of parsing a task's parameters,
validating them, and generating the task's files (like testcases).

A TaskProcessor can be given the task parameters as a Python module,
or a YAML file. The former is "unsafe", and should run locally or in a
sandbox on the server; it is used to generate the testcases, so it runs
arbitrary code. The latter is safe, and can be used after the sandbox
is done, in order to inspect the generated content.

The generated content includes:
- module.yaml, containing similar contents to module.py but without code.
- Compiled checker.
- Generate testcases.
- Compiled solution, if relevant for generating output.
"""

import argparse
import imp
import os
import subprocess
import sys
import yaml


class Constants(object):
    """
    Task and validation related constants.
    """

    types = {"Batch", "OutputOnly", "TwoSteps"}
    min_time = 0.5
    max_time = 10
    min_memory = 16
    max_memory = 1024
    min_subtasks = 1
    max_subtasks = 100
    min_subtask_testcases = 1
    max_subtask_testcases = 200
    min_total_testcases = 1
    max_total_testcases = 200
    min_subtask_score = 0
    max_subtask_score = 100
    max_attachments = 100
    max_auto_submits = 30
    max_auto_submit_len = 30
    max_auto_submit_score = 1000
    source_exts = {".c", ".cpp", ".cxx", ".cs", ".java"}
    headers_exts = {".h"}
    output_generator_exts = {".c", ".cpp", ".cxx"}
    checker_exts = {".c", ".cpp", ".cxx"}
    statement_exts = {".pdf"}
    statement_langs = {"he", "en"}
    gen_check_ignore_exts = {".lyx", ".pdf", ".doc", ".docx", ".txt"}
    gen_check_ignore_dirs = {"auto.gen"}

    @staticmethod
    def input_namer(subtask_index, subtask_testcase_index, _=None):
        """
        Default input namer: <subtask>.<testcase>.in (1-based)
        """
        return "%02d.%02d.in" % (subtask_index + 1, subtask_testcase_index + 1)

    @staticmethod
    def output_namer(subtask_index, subtask_testcase_index, _=None):
        """
        Default output namer: <subtask>.<testcase>.out (1-based)
        """
        return "%02d.%02d.out" % (subtask_index + 1,
                                  subtask_testcase_index + 1)


class Validator(object):
    """
    Validation methods for task parameters and all their internal parts.
    """

    @staticmethod
    def number(number, allow_float=False, min_val=None, max_val=None):
        """
        Check if the given object is a number, with optional range check.
        """
        is_int = isinstance(number, int)
        is_float = isinstance(number, float)
        if not is_int and not is_float:
            return False
        if not is_int and not allow_float:
            return False
        if min_val is not None and number < min_val:
            return False
        if max_val is not None and number > max_val:
            return False
        return True

    @staticmethod
    def string(string, min_len=None, max_len=None):
        """
        Check if the given object is a string, with optional length check.
        """
        if not isinstance(string, basestring):
            return False
        if min_len is not None and len(string) < min_len:
            return False
        if max_len is not None and len(string) > max_len:
            return False
        return True

    @staticmethod
    def file(path, base_dir=None):
        """
        Check if the given path is a valid, existing file.
        Paths must be relative to base_dir if it is not None.
        """
        if not Validator.string(path):
            return False
        if base_dir is not None:
            path = os.path.join(base_dir, path)

            # Security check: make sure the given path is actually
            # inside the base directory. This prevents exposing server
            # files when developing a task.
            path = os.path.realpath(path)
            if not path.startswith(base_dir):
                return False

        return os.path.isfile(path)

    @staticmethod
    def dir(path, base_dir=None):
        """
        Check if the given path is a valid, existing directory.
        Paths must be relative to base_dir if it is not None.
        """
        if not Validator.string(path):
            return False
        if base_dir is not None:
            path = os.path.join(base_dir, path)

            # Security check: make sure the given path is actually
            # inside the base directory. This prevents exposing server
            # files when developing a task.
            path = os.path.realpath(path)
            if not path.startswith(base_dir):
                return False

        return os.path.isdir(path)

    @staticmethod
    def dict(dictionary, min_len=None, max_len=None):
        """
        Check if the given object is a dictionary, with optional size check.
        """
        if not isinstance(dictionary, dict):
            return False
        if min_len is not None and len(dictionary) < min_len:
            return False
        if max_len is not None and len(dictionary) > max_len:
            return False
        return True

    @staticmethod
    def list(items, min_len=None, max_len=None):
        """
        Check if the given object is a list, with optional length check.
        """
        if not isinstance(items, list):
            return False
        if min_len is not None and len(items) < min_len:
            return False
        if max_len is not None and len(items) > max_len:
            return False
        return True

    @staticmethod
    def strings_list(strings, min_list_len=None, max_list_len=None,
                     min_str_len=None, max_str_len=None):
        """
        Check if the given object is a list of strings, with optional
        size check for the list and for each string.
        """
        if not Validator.list(strings, min_list_len, max_list_len):
            return False
        return all(Validator.string(string, min_str_len, max_str_len)
                   for string in strings)

    @staticmethod
    def files_list(paths, min_list_len=None, max_list_len=None,
                   base_dir=None):
        """
        Check if the given object is a list of valid, existing file paths,
        with optional list length check.
        Paths are checked with respect to base_dir if it is not None.
        """

        if not Validator.strings_list(paths, min_list_len, max_list_len):
            return False
        return all(Validator.file(path, base_dir=base_dir) for path in paths)

    @staticmethod
    def numbers_list(numbers, min_list_len=None, max_list_len=None,
                     min_val=None, max_val=None):
        """
        Check if the given object is a list of numbers, with optional
        range check.
        """

        if not Validator.list(numbers, min_list_len, max_list_len):
            return False
        return all(Validator.number(number, min_val=min_val, max_val=max_val)
                   for number in numbers)

    @staticmethod
    def assert_key_exists(container, key):
        """
        Check if the given dictionary/set contains the given key.
        Raise an exception if not.
        """
        if key not in container:
            raise Exception("Could not find key: %s" % key)

    @staticmethod
    def assert_type(value, _type, name):
        """
        Check if the given object has the given type.
        Raise an exception if not.
        """
        if not isinstance(value, _type):
            raise Exception("%s is of type %s, expected: %s." %
                            (name, type(object), _type))

    @staticmethod
    def assert_value(value, _type, name, **kwargs):
        """
        Check if the given object is of the given type.

        If the type is one of: "number", "string", "dict", "file", "dir",
        "files_list", "strings_list", then the corresponding
        Validator function is executed with the given keyword arguments.
        Otherwise, it is checked that type(object) is the given type.

        Raise an exception if not.
        """

        validate_func = None
        if _type == "string":
            validate_func = Validator.string
        elif _type == "dict":
            validate_func = Validator.dict
        elif _type == "number":
            validate_func = Validator.number
        elif _type == "file":
            validate_func = Validator.file
        elif _type == "dir":
            validate_func = Validator.dir
        elif _type == "list":
            validate_func = Validator.list
        elif _type == "strings_list":
            validate_func = Validator.strings_list
        elif _type == "files_list":
            validate_func = Validator.files_list
        elif _type == "numbers_list":
            validate_func = Validator.numbers_list

        if validate_func is None:
            Validator.assert_type(value, _type, name)
        elif not validate_func(value, **kwargs):
            raise Exception("%s should be a valid %s, but it is: %s.\n"
                            "Check validity of paths, ranges, sizes.\n"
                            "Arguments: %s" %
                            (name, _type, value, kwargs))

    @staticmethod
    def assert_task_type(params):
        """
        Check if the task type in the given parameters is valid.
        Raise an exception if not.
        """
        Validator.assert_key_exists(params, "type")
        Validator.assert_key_exists(Constants.types, params["type"])

    @staticmethod
    def assert_task_limits(params):
        """
        Check if the time and memory in the given task params are valid.
        Raise an exception if not.
        """
        Validator.assert_key_exists(params, "time")
        Validator.assert_value(params["time"], "number", "time",
                               allow_float=True,
                               min_val=Constants.min_time,
                               max_val=Constants.max_time)
        Validator.assert_key_exists(params, "memory")
        Validator.assert_value(params["memory"], "number", "memory",
                               allow_float=False,
                               min_val=Constants.min_memory,
                               max_val=Constants.max_memory)

    @staticmethod
    def assert_task_attachments(params, task_dir):
        """
        Check if the attachments in the params is a valid list of files.
        If base_dir is given, it is checked that files exist.
        Raise an exception if the list is invalid.

        If the task contains no attachments, do nothing.
        """
        if "attachments" not in params:
            return

        attachments = params["attachments"]
        Validator.assert_value(attachments, "files_list", "attachments",
                               max_list_len=Constants.max_attachments,
                               base_dir=task_dir)

    @staticmethod
    def assert_task_graders(params, task_dir):
        """
        Check if the graders list in the params is a valid list of files.
        If it is not, raise an exception.

        If no graders are specified, do nothing.
        """
        if "graders" not in params:
            return

        # Make sure it is a list of files.
        graders = params["graders"]
        Validator.assert_value(graders, "files_list", "graders",
                               base_dir=task_dir)

        # Make sure every grader corresponds to a unique allowed language.
        ext_set = set()
        for grader in graders:
            _, ext = os.path.splitext(grader)
            if ext not in Constants.source_exts:
                raise Exception("Unknown grader extension: %s" % ext)
            if ext in ext_set:
                raise Exception("Duplicate grader type: %s" % ext)
            ext_set.add(ext)

    @staticmethod
    def assert_task_managers(params, task_dir):
        """
        Check if the managers list in the params is a valid list of files.
        If it is not, raise an exception.

        If no managers are specified, do nothing.
        """
        if "managers" not in params:
            return

        # Make sure it is a list of files.
        managers = params["managers"]
        Validator.assert_value(managers, "files_list", "managers",
                               base_dir=task_dir)

        # Manager must be a source file.
        for manager in managers:
            _, ext = os.path.splitext(manager)
            if ext not in Constants.source_exts:
                raise Exception("Unknown manager extension: %s" % ext)

    @staticmethod
    def assert_task_headers(params, task_dir):
        """
        Check if the headers list in the params is a valid list of files.
        If it is not, raise an exception.

        If no headers are specified, do nothing.
        """
        if "headers" not in params:
            return

        # Make sure it is a list of files.
        headers = params["headers"]
        Validator.assert_value(headers, "files_list", "headers",
                               base_dir=task_dir)

        # Make sure all headers have valid extensions.
        for header in headers:
            _, ext = os.path.splitext(header)
            if ext not in Constants.headers_exts:
                raise Exception("Unknown header extension: %s" % ext)

    @staticmethod
    def assert_task_output_generator(params, task_dir):
        """
        Check if the output generator in the params is a valid C++ file.
        If it is not, raise an exception.

        If not specified, do nothing.
        """
        if "output_generator" not in params:
            return

        # Check if it is a valid file.
        output_generator = params["output_generator"]
        Validator.assert_value(output_generator, "file", "output_generator",
                               base_dir=task_dir)

        # Check that it is a C++ file.
        _, ext = os.path.splitext(output_generator)

        if ext not in Constants.output_generator_exts:
            raise Exception("Unknown generator extension: %s" % ext)

    @staticmethod
    def assert_task_checker(params, task_dir, gen_dir=None):
        """
        Check if the checker in the params is a valid C++ file.
        If it is not, raise an exception.
        In the gen_dir it should be named "checker" (no extension).

        If not specified, do nothing.
        """
        if "checker" not in params:
            return

        # Check if it is a valid file.
        checker = params["checker"]
        Validator.assert_value(checker, "file", "checker", base_dir=task_dir)

        # Check that it is a C++ file.
        _, ext = os.path.splitext(checker)

        if ext not in Constants.checker_exts:
            raise Exception("Unknown generator extension: %s" % ext)

        # Compiled "checker" must exist in generated directory.
        if gen_dir is not None:
            Validator.assert_value("checker", "file", "checker",
                                   base_dir=gen_dir)

    @staticmethod
    def assert_task_statements(params, task_dir):
        """
        Check if the list of statements in the params is valid.
        If it is not, raise an exception.

        If not specified, do nothing.
        """
        if "statements" not in params:
            return

        # Check that it is a list.
        statements = params["statements"]
        Validator.assert_type(statements, list, "statements")

        languages = set()
        for statement_info in statements:

            # Each statement must be a dictionary with "language" and "path".
            Validator.assert_type(statement_info, dict, "statement_info")
            if "language" not in statement_info:
                raise Exception("Statement must specify language.")
            if "path" not in statement_info:
                raise Exception("Statement must specify path.")

            language = statement_info["language"]
            path = statement_info["path"]

            # Make sure each statement language is valid.
            if language not in Constants.statement_langs:
                raise Exception("Unknown statement language: '%s'. "
                                "Must be one of: %s." %
                                (language, str(Constants.statement_langs)))

            # Make sure each statement language is unique.
            if language in languages:
                raise Exception("Statement language collision: %s" % language)
            languages.add(language)

            # Make sure it is a PDF.
            _, ext = os.path.splitext(path)
            if ext not in Constants.statement_exts:
                raise Exception("Unknown statement extension: %s. "
                                "Must be one of: %s" %
                                (ext, str(Constants.statement_exts)))

            # Make sure it is a valid file.
            Validator.assert_value(path, "file", "statement",
                                   base_dir=task_dir)

    @staticmethod
    def assert_testcase(params, subtask_index, subtask_testcase_index,
                        total_testcase_index, task_dir, gen_dir=None):
        """
        Check if the given testcase is valid.
        If gen_dir is specified, the input file is expected to be
        testcase["input"] under gen_dir (similarly for output).

        If gen_dir is not specified, but the testcases are supposed to exist
        ("existing_testcases_format" is a dictionary), then the "input" field
        of the dictionary is used as a function to get the input file name.
        The function receives subtask_index, subtask_testcase_index, and
        total_testcase_index.
        """

        # Input and output are named using functions, and expected to exist.
        existing_format = params.get("existing_testcases_format")
        if isinstance(existing_format, dict):
            input_namer = existing_format["input"]
            output_namer = existing_format["output"]
            input_name = input_namer(subtask_index, subtask_testcase_index,
                                     total_testcase_index)
            output_name = output_namer(subtask_index, subtask_testcase_index,
                                       total_testcase_index)
            Validator.assert_value(input_name, "file", "input",
                                   base_dir=task_dir)
            Validator.assert_value(output_name, "file", "output",
                                   base_dir=task_dir)
            return

        testcases = params["subtasks"][subtask_index]["testcases"]
        testcase = testcases[subtask_testcase_index]

        # Input and output are expected to be generated, and the testcase
        # contains "input" and "output" paths.
        if gen_dir is not None:
            input_name = testcase["input"]
            output_name = testcase["output"]
            Validator.assert_value(input_name, "file", "input",
                                   base_dir=task_dir)
            Validator.assert_value(output_name, "file", "output",
                                   base_dir=task_dir)
            return

        # Input and output are not expected to be generated.
        # The testcase is simply a dictionary.
        Validator.assert_value(testcase, "dict", "testcase")

    @staticmethod
    def assert_subtask(params, subtask_index, acc_testcases, task_dir,
                       gen_dir=None):
        """
        Check if the given subtask inside the task params is valid.
        Raise an exception if not.
        acc_testcases is the number of testcases preceding this subtask,
        so that for each testcase we have its overall index.

        Return the number of testcases in the subtask.
        """
        subtask = params["subtasks"][subtask_index]
        if not Validator.dict(subtask):
            raise Exception("Subtask must be a dictionary.")

        # Score.
        if "score" not in subtask:
            raise Exception("Subtask must specify score.")

        score = subtask["score"]
        Validator.assert_value(score, "number", "subtask score",
                               allow_float=False,
                               min_val=Constants.min_subtask_score,
                               max_val=Constants.max_subtask_score)

        # Other subtasks contained in it.
        # Each subtask can contain previous subtasks (1-based indices).
        if "contains" in subtask:
            other_subtasks = subtask["contains"]
            Validator.assert_value(other_subtasks,
                                   "numbers_list",
                                   "contained subtasks",
                                   max_list_len=subtask_index,
                                   min_val=1,
                                   max_val=subtask_index)

        # Existing testcases.
        if "existing_testcases_format" in params:
            if "num_testcases" not in subtask:
                raise Exception("Subtask must contain key 'num_testcases', "
                                "because 'existing_testcases_format' "
                                "is given")
            num_testcases = subtask["num_testcases"]
        # Testcases to be generated.
        else:
            if "testcases" not in subtask:
                raise Exception("Subtask must contain key 'testcases'.")
            testcases = subtask["testcases"]
            Validator.assert_value(testcases, "list", "testcases")
            num_testcases = len(testcases)

        Validator.assert_value(num_testcases, "number", "num_testcases",
                               allow_float=False,
                               min_val=Constants.min_subtask_testcases,
                               max_val=Constants.max_subtask_testcases)

        for index in xrange(num_testcases):
            Validator.assert_testcase(params, subtask_index, index,
                                      acc_testcases + index,
                                      task_dir=task_dir,
                                      gen_dir=gen_dir)
        return num_testcases

    @staticmethod
    def assert_task_subtasks(params, task_dir, gen_dir=None):
        """
        Check if the subtasks in the task params are valid.
        Raise an exception if not.
        """
        if "subtasks" not in params:
            raise Exception("Missing 'subtasks' in the task params.")
        subtasks = params["subtasks"]

        if not Validator.list(subtasks, Constants.min_subtasks,
                              Constants.max_subtasks):
            raise Exception("Subtasks should be a list of reasonable size.")

        acc_testcases = 0
        for index in xrange(len(subtasks)):
            num_testcases = Validator.assert_subtask(params, index,
                                                     acc_testcases,
                                                     task_dir=task_dir,
                                                     gen_dir=gen_dir)
            acc_testcases += num_testcases

    @staticmethod
    def assert_auto_submit(params, task_dir):
        """
        Check if the "auto_submit" field is a valid list of submissions.
        If it is not, raise an exception.

        If not specified, do nothing.
        """

        if "auto_submit" not in params:
            return

        submit_items = params["auto_submit"]

        if not Validator.list(submit_items, 0, Constants.max_auto_submits):
            raise Exception("Expected \"auto_submit\" to be a list of"
                            " up to %s items." % len(submit_items))

        if not submit_items:
            return

        if params["type"] != "Batch":
            raise Exception("Auto submit only supported in "
                            "batch tasks currently.")

        # The number of files per submission. Update this when adding
        # support for other task types.
        num_submission_files = 1

        for submit_item in submit_items:
            # A submission item has 3 fields: name, score, files.
            Validator.assert_value(submit_item, "dict", "auto submit item",
                                   min_len=3, max_len=3)

            name = submit_item.get("name")
            score = submit_item.get("score")
            files = submit_item.get("files")
            Validator.assert_value(name, "string", "auto submit name",
                                   min_len=1,
                                   max_len=Constants.max_auto_submit_len)
            Validator.assert_value(score, "number", "auto submit score",
                                   allow_float=True, min_val=0,
                                   max_val=Constants.max_auto_submit_score)
            Validator.assert_value(files, "files_list", "auto submit files",
                                   base_dir=task_dir,
                                   min_list_len=num_submission_files,
                                   max_list_len=num_submission_files)

            # When supporting output only tasks, consider
            # allowing text files here.
            for path in files:
                _, ext = os.path.splitext(path)
                if ext not in Constants.source_exts:
                    raise Exception("Auto submit file must have a "
                                    "valid source file extension.")

    @staticmethod
    def assert_task_params(params, task_dir, gen_dir=None):
        """
        Validate the given task parameters dictionary.
        If any parameters are missing or have invalid types, raise an
        exception with an appropriate message.

        task_dir is the directory of the task files.
        gen_dir (optional) is the directory where the automatically generated
        files can be found.

        If gen_dir is given:
        - If the task uses a checker, then it is verified that gen_dir/checker
          exists.
        - If the testcases don't exist in the task dir (i.e.
          "existing_testcases_format" is not given), then it is verified
          that they exist inside gen_dir. Each testcase is expected to be
          a dictionary containing "input" and "output" fields which are files
          in gen_dir.
        """

        # Params sanity checks.
        Validator.assert_type(params, dict, "task params")
        if not os.path.isdir(task_dir):
            raise Exception("Expected valid dir: %s" % task_dir)

        # Task type
        Validator.assert_task_type(params)

        # Limits
        need_limits = (params["type"] != "OutputOnly")
        if need_limits:
            Validator.assert_task_limits(params)

        # Everything else in the task directory.
        Validator.assert_task_attachments(params, task_dir)
        Validator.assert_task_graders(params, task_dir)
        Validator.assert_task_managers(params, task_dir)
        Validator.assert_task_headers(params, task_dir)
        Validator.assert_task_statements(params, task_dir)
        Validator.assert_task_output_generator(params, task_dir)
        Validator.assert_auto_submit(params, task_dir)

        # These properties are special: if gen_dir is given,
        # we expect the corresponding generated files to exist.
        Validator.assert_task_checker(params, task_dir, gen_dir)
        Validator.assert_task_subtasks(params, task_dir, gen_dir)


class TaskProcessor(object):
    """
    An object in charge of processing a task, validating it,
    and generating relevant files for it.
    """

    def __init__(self, params_source, task_dir, post_gen_dir=None):
        """
        Create a new task processor. params_source can be a path
        to a .yaml file suitable for safe loading, or a .py file
        suitable for unsafe module importing. If params_source is a
        dictionary, it is taken to be the params themselves.

        If this task is already generated, post_gen_dir will be used
        to validate the existing generated files.
        """
        self.task_dir = task_dir
        self._load_params(params_source)
        Validator.assert_task_params(self.params, task_dir, post_gen_dir)

    def _load_params(self, params_source):
        """
        Load the task parameters from a given source, as described
        in the constructor.
        """
        if isinstance(params_source, dict):
            self.params = params_source
            self.module = None
        elif isinstance(params_source, basestring):
            _, ext = os.path.splitext(params_source)
            if ext == ".yaml":
                with open(params_source) as stream:
                    self.params = yaml.safe_load(stream)
                self.module = None
            elif ext == ".py":
                self.module = imp.load_source("module", params_source)
                self.params = self.module.get_task_params()
            else:
                raise Exception("Unsupported params file: %s" % params_source)
        else:
            raise Exception("Unsupported params format: %s" % params_source)

    def generate_testcases(self, gen_dir):
        """
        Generate the testcases for this task.
        If the testcases are supposed to already exist in the task directory,
        do nothing.

        If output_generator is present in the task params, compile it
        and use it to generate output in testcases that don't specify
        "output".
        """
        if self.module is None:
            raise Exception("Cannot generate testcases without a module.")

        if "existing_testcases_format" in self.params:
            return

        # Compile generator if needed.
        if "output_generator" in self.params:
            source_name = self.params["output_generator"]
            source_path = os.path.join(self.task_dir, source_name)
            self.generator = os.path.join(gen_dir, "generator.out")
            TaskProcessor.compile_cpp([source_path], self.generator)
        else:
            self.generator = None

        subtasks = self.params["subtasks"]
        for subtask_index in xrange(len(subtasks)):
            testcases = subtasks[subtask_index]["testcases"]
            for testcase_index in xrange(len(testcases)):
                testcase = testcases[testcase_index]
                self._generate_testcase(testcase, subtask_index,
                                        testcase_index,
                                        gen_dir)

    def _generate_testcase(self, testcase, subtask_index,
                           subtask_testcase_index,
                           gen_dir):
        """
        Generate the given testcase, and put the input and output files
        in gen_dir. Their names are defined in the Constants class.
        If a generator was set, use it to generate the output.
        The input is given via stdin.

        The task module must contain a function "generate_testcase",
        which receives the same arguments as the testcase dictionary.
        It is invoked as generate_testcase(**testcase).

        If the generated testcase does not contain an "input" string,
        or the output generation is not successful, an exception is raised.
        """

        input_name = Constants.input_namer(subtask_index,
                                           subtask_testcase_index)
        output_name = Constants.output_namer(subtask_index,
                                             subtask_testcase_index)
        input_path = os.path.join(gen_dir, input_name)
        output_path = os.path.join(gen_dir, output_name)

        testcase_io = self.module.generate_testcase(**testcase)
        if "input" not in testcase_io:
            raise Exception("Testcase must contain 'input' key.")

        with open(input_path, "w") as stream:
            stream.write(testcase_io["input"])

        if "output" in testcase_io:
            with open(output_path, "w") as stream:
                stream.write(testcase_io["output"])
        else:
            if self.generator is None:
                raise Exception("Testcase did not specify output, "
                                "but an output generator was not found.")
            TaskProcessor.run_io([self.generator],
                                 input_path=input_path,
                                 output_path=output_path)

    def generate_checker(self, gen_dir):
        """
        Compile the checker for this task.
        If no checker is specified, do nothing.

        The checker is put in gen_dir/checker. If compilation fails,
        raise an exception.
        """
        if "checker" not in self.params:
            return

        source_path = os.path.join(self.task_dir, self.params["checker"])
        out_path = os.path.join(gen_dir, "checker")
        TaskProcessor.compile_cpp([source_path], out_path)

    def generate_yaml(self, gen_dir, yaml_path):
        """
        Dump the task parameters to a safe YAML file.
        This converts all possibly unsafe fields to safe.
        Such fields may be only:
        - existing_testcases_format (which is allowed to contain functions):
          if it is present, it is replaced with True (boolean).
        - testcases: each testcase is replaced with a dictionary containing
          "input" and "output" fields that describe the file paths.
        """
        with open(yaml_path, "w") as stream:
            stream.write(self._get_safe_yaml(gen_dir))

    def _get_safe_yaml(self, gen_dir):
        """
        Create and return a YAML-safe dictionary (no Python objects)
        based on the task params. See dump_yaml documentation.

        Raise an exception if something goes wrong, notably when
        yaml.safe_dump fails.
        """

        # We work on a shallow copy.
        params_copy = dict(self.params)

        # Determine whether the testcases already exist.
        # If so, replace "existing_testcases_format" with True.
        existing = "existing_testcases_format" in params_copy
        if existing:
            params_copy["existing_testcases_format"] = True

        # The default input/output file names are taken from Constants.
        # They are overridden by params if needed.
        input_namer = Constants.input_namer
        output_namer = Constants.output_namer
        if existing:
            input_namer = self.params["existing_testcases_format"]["input"]
            output_namer = self.params["existing_testcases_format"]["output"]

        # Rewrite the subtasks' testcases with file names.
        params_copy["subtasks"] = []
        acc_testcases = 0
        subtasks = self.params["subtasks"]
        for subtask_index in xrange(len(subtasks)):
            subtask = subtasks[subtask_index]

            # Get the number of testcases.
            if existing:
                num_testcases = subtask["num_testcases"]
            else:
                num_testcases = len(subtask["testcases"])

            # Get the list of other subtasks contained in it.
            if "contains" in subtask:
                other_subtasks = subtask["contains"]
            else:
                other_subtasks = []

            # Make a safe copy of the subtask.
            subtask_copy = {
                "score": subtask["score"],
                "testcases": [],
                "num_testcases": num_testcases,
                "contains": other_subtasks
            }

            # Add all testcases, converted to the format of describing
            # file names instead of the content.
            for subtask_testcase_index in xrange(num_testcases):
                # Get the file name of this testcase. If the file is supposed
                # to exist under task_dir, the names from the params'
                # "existing_testcases_format" functions are used.
                total_testcase_index = subtask_testcase_index + acc_testcases
                input_name = input_namer(subtask_index,
                                         subtask_testcase_index,
                                         total_testcase_index)
                output_name = output_namer(subtask_index,
                                           subtask_testcase_index,
                                           total_testcase_index)

                # Existing testcases are based in task_dir, generated
                # one are in gen_dir.
                if existing:
                    input_path = os.path.join(self.task_dir, input_name)
                    output_path = os.path.join(self.task_dir, output_name)
                else:
                    input_path = os.path.join(gen_dir, input_name)
                    output_path = os.path.join(gen_dir, output_name)

                # Add the paths to the safe copy.
                subtask_copy["testcases"] += [{
                    "input": input_path,
                    "output": output_path
                }]

            # Update accumulating testcases.
            acc_testcases += num_testcases

            # Put the safe subtask copy in the safe params.
            params_copy["subtasks"] += [subtask_copy]

        # Convert the safe copy to a string. This guarantees we fail
        # if we missed anything.
        return yaml.safe_dump(params_copy)

    def generate_all(self, gen_dir, yaml_path=None):
        """
        Generate everything to the given gen_dir.
        The YAML file is written to gen_dir/module.yaml by default.

        After generation, the file "gen.ok" is created.
        If the file already exists and there are no files more recent
        than it in the task directory, do nothing.

        The file "gen.error" is created initially, and deleted before
        returning. So if it exists, there were errors.
        """

        if not TaskProcessor.needs_generating(self.task_dir, gen_dir):
            return

        TaskProcessor.mark_error(gen_dir)

        if yaml_path is None:
            yaml_path = os.path.join(gen_dir, "module.yaml")
        self.generate_yaml(gen_dir, yaml_path)
        self.generate_checker(gen_dir)
        self.generate_testcases(gen_dir)

        TaskProcessor.mark_ok(gen_dir)

    def get_task_type(self):
        """
        Return the type of this task: "Batch"/"OutputOnly"/"TwoSteps".
        """
        return self.params["type"]

    def get_time(self):
        """
        Return the time limit for this task.
        """
        return self.params["time"]

    def get_memory(self):
        """
        Return the memory limit for this task.
        """
        return self.params["memory"]

    def get_statements(self):
        """
        Return a list of statements for this task, in the same format as
        in the task module, but with absolute paths.
        """
        if "statements" not in self.params:
            return []

        result = []
        statements = self.params["statements"]
        for statement_info in statements:
            language = statement_info["language"]
            path = statement_info["path"]
            result += [{
                "language": language,
                "path": os.path.abspath(os.path.join(self.task_dir, path))
            }]
        return result

    def get_attachments(self):
        """
        Return a list of attachments for this task, in absolute paths.
        """
        if "attachments" not in self.params:
            return []

        attachments = self.params["attachments"]
        return [os.path.abspath(os.path.join(self.task_dir, path))
                for path in attachments]

    def get_graders(self):
        """
        Return the list of graders, in absolute paths.
        """
        if "graders" not in self.params:
            return []

        graders = self.params["graders"]
        return [os.path.abspath(os.path.join(self.task_dir, path))
                for path in graders]

    def get_headers(self):
        """
        Return the list of headers, in absolute paths.
        """
        if "headers" not in self.params:
            return []

        headers = self.params["headers"]
        return [os.path.abspath(os.path.join(self.task_dir, path))
                for path in headers]

    def get_managers(self):
        """
        Return the list of managers, in absolute paths.
        """
        if "managers" not in self.params:
            return []

        managers = self.params["managers"]
        return [os.path.abspath(os.path.join(self.task_dir, path))
                for path in managers]

    def get_subtasks(self):
        """
        Return the list of subtasks.
        """
        return self.params["subtasks"]

    def get_auto_submit_items(self):
        """
        Return the list of auto submit items, in absolute paths.
        """
        if "auto_submit" not in self.params:
            return []

        # Create the submission items with absolute paths.
        items = self.params["auto_submit"]
        new_items = []
        for item in items:
            new_files = [os.path.abspath(os.path.join(self.task_dir, path))
                         for path in item["files"]]
            new_item = {"name": item["name"], "score": item["score"],
                        "files": new_files}
            new_items += [new_item]
        return new_items

    def has_checker(self):
        """
        Return whether this task uses a checker.
        """
        return "checker" in self.params

    def has_grader(self):
        """
        Return whether this task uses a grader.
        """
        return "graders" in self.params

    @staticmethod
    def run(commands, input_string="", fail_abort=True):
        """
        Run the given commands as a subprocess, wait for it to finish.
        If fail_abort is set, then a non-zero return code will trigger
        an exception.
        Return (return_code, stdout, stderr).
        """
        process = subprocess.Popen(commands,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(input=input_string)
        return_code = process.returncode
        if return_code != 0 and fail_abort:
            raise Exception("Command returned non-zero: %s" % commands)
        return (return_code, stdout, stderr)

    @staticmethod
    def run_io(commands, input_path=None, output_path=None, error_path=None,
               fail_abort=True):
        """
        Run the given commands as a subprocess, wait for it to finish.
        If input/output/error paths are given, stdin/stdout/stderr are
        redirected to those files. If fail_abort is set, then a non-zero
        return code will trigger an exception.
        Return (return_code, stdout, stderr), but note that file redirection
        may make stdout/stderr empty.
        """
        if input_path is not None:
            input_stream = open(input_path)
        else:
            input_stream = subprocess.PIPE
        if output_path is not None:
            output_stream = open(output_path, "w")
        else:
            output_stream = subprocess.PIPE
        if error_path is not None:
            error_stream = open(error_path, "w")
        else:
            error_stream = subprocess.PIPE
        process = subprocess.Popen(commands,
                                   stdin=input_stream,
                                   stdout=output_stream,
                                   stderr=error_stream)
        stdout, stderr = process.communicate()
        return_code = process.returncode

        if input_stream != subprocess.PIPE:
            input_stream.close()
        if output_stream != subprocess.PIPE:
            output_stream.close()
        if error_stream != subprocess.PIPE:
            error_stream.close()

        if return_code != 0 and fail_abort:
            raise Exception("Command returned non-zero: %s\n"
                            "Return code: %s\n"
                            "Stdout: %s\n"
                            "Stderr: %s\n" %
                            (commands, return_code, stdout, stderr))
        return (return_code, stdout, stderr)

    @staticmethod
    def compile_cpp(sources, out_path):
        """
        Compile the given C++ sources. The executable is named according to
        out_path. Raise an exception if compilation failed.

        Return the stderr output of g++.
        """
        base_command = ["/usr/bin/g++", "-Wall", "-O2", "-std=c++0x", "-o"]
        _, _, stderr = TaskProcessor.run(base_command + [out_path] + sources)
        return stderr

    @staticmethod
    def touch(path):
        """
        Touch a file, like the Unix touch command.
        """
        with open(path, "a"):
            os.utime(path, None)

    @staticmethod
    def mark_error(gen_dir):
        """
        Mark the given generation directory as having an error.
        This touches a file "gen.error", and removes "gen.ok"
        if present.
        """
        gen_error = os.path.join(gen_dir, "gen.error")
        gen_ok = os.path.join(gen_dir, "gen.ok")
        TaskProcessor.touch(gen_error)
        if os.path.isfile(gen_ok):
            os.remove(gen_ok)

    @staticmethod
    def mark_ok(gen_dir):
        """
        Mark the given generation directory as okay.
        This touches a file "gen.ok", and removes "gen.error"
        if present.
        """
        gen_error = os.path.join(gen_dir, "gen.error")
        gen_ok = os.path.join(gen_dir, "gen.ok")
        TaskProcessor.touch(gen_ok)
        if os.path.isfile(gen_error):
            os.remove(gen_error)

    @staticmethod
    def needs_generating(task_dir, gen_dir):
        """
        Check whether this task needs to be generated.
        A task needs to be generated under any one of the conditions:
        - The generation directory was marked as having an error.
        - The generation directory was not marked as okay.
        - There is a file newer than gen.ok in the task directory.
          Irrelevant directories and files aren't traversed.
        """
        gen_error = os.path.join(gen_dir, "gen.error")
        gen_ok = os.path.join(gen_dir, "gen.ok")
        if os.path.isfile(gen_error) or not os.path.isfile(gen_ok):
            return True

        # Last generating time.
        last_ok_time = os.path.getmtime(gen_ok)

        # We traverse the task directory. Top down means we can change
        # the list of directories in place. We use this to skip irrelevant
        # directories.
        for (root, dirs, files) in os.walk(task_dir, topdown=True):
            # Change the list of directories in place (slice assignment).
            dirs[:] = [dirname for dirname in dirs
                       if not TaskProcessor.is_dir_irrelevant(root, dirname)]

            for filename in files:
                if TaskProcessor.is_file_irrelevant(root, filename):
                    continue
                file_path = os.path.join(root, filename)
                if os.path.getmtime(file_path) > last_ok_time:
                    return True

        return False

    @staticmethod
    def is_file_irrelevant(_, filename):
        """
        Check if the given file is irrelevant for task generation.
        This is used to skip files when checking if the task changed.
        """
        if filename.startswith("."):
            return True

        _, ext = os.path.splitext(filename)
        return ext in Constants.gen_check_ignore_exts

    @staticmethod
    def is_dir_irrelevant(_, dirname):
        """
        Check if the given directory is irrelevant for task generation.
        This is used to skip files when checking if the task changed.
        """
        return dirname.startswith(".") or \
            dirname in Constants.gen_check_ignore_dirs


def main():
    """
    Execute task processing.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--params_file", help="params file (py/yaml).",
                        default=None, required=True)
    parser.add_argument("--task_dir", help="task directory to work on.",
                        default=None)
    parser.add_argument("--gen_dir", help="generation directory to work on.",
                        default=None)
    parser.add_argument("--generate_all", help="generate all task files.",
                        default=None, action="store_true")
    args = parser.parse_args()

    params_file = args.params_file

    if args.generate_all:
        if args.gen_dir is None or args.task_dir is None:
            parser.error("generating all requires task_dir and gen_dir.")
        if not os.path.isdir(args.task_dir):
            parser.error("not a valid directory: %s" % args.task_dir)
        if not os.path.isdir(args.gen_dir):
            parser.error("not a valid directory: %s" % args.gen_dir)

        processor = TaskProcessor(params_file, args.task_dir)
        processor.generate_all(args.gen_dir)

    return 0

if __name__ == "__main__":
    sys.exit(main())
