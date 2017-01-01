"""
.. module:: core
   :synopsis: Main module for oct2py package.
              Contains the core session object Oct2Py

.. moduleauthor:: Steven Silvester <steven.silvester@ieee.org>

"""
from __future__ import print_function
import os
import tempfile
import warnings

import numpy as np
from metakernel.pexpect import EOF
from octave_kernel.kernel import OctaveEngine

from oct2py.matwrite import write_file
from oct2py.matread import read_file
from oct2py.utils import (
    get_nout, Oct2PyError, get_log)
from oct2py.compat import unicode, input
from oct2py.dynamic import (
    _make_function_ptr_instance, _make_variable_ptr_instance,
    _make_user_class, OctavePtr)


# TODO: handling of timeout and interrupt
#       update the magic error handling
#       add a better traceback
#       get tests to pass
#       add tests for:
#            get_pointer - variable, function, class, object instance
#            set_plot_settings
#            pull - object
#            feval - store_as, variable ptr, function ptr, class ptr,
#                    object instance ptr

class Oct2Py(object):

    """Manages an Octave session.

    Uses MAT files to pass data between Octave and Numpy.
    The function must either exist as an m-file in this directory or
    on Octave's path.
    The first command will take about 0.5s for Octave to load up.
    The subsequent commands will be much faster.

    You may provide a logger object for logging events, or the oct2py.get_log()
    default will be used.  Events will be logged as debug unless verbose is set
    when calling a command, then they will be logged as info.

    Parameters
    ----------
    executable : str, optional
        Name of the Octave executable, can be a system path.  If this is not
        given, we look for an OCTAVE_EXECUTABLE environmental variable.
        The fallback is to call "octave-cli" or "octave".
    logger : logging object, optional
        Optional logger to use for Oct2Py session
    timeout : float, optional
        Timeout in seconds for commands
    oned_as : {'row', 'column'}, optional
        If 'column', write 1-D numpy arrays as column vectors.
        If 'row', write 1-D numpy arrays as row vectors.}
    temp_dir : str, optional
        If specified, the session's MAT files will be created in the
        directory, otherwise a default directory is used.  This can be
        a shared memory (tmpfs) path.
    convert_to_float : bool, optional
        If true, convert integer types to float when passing to Octave.
    """

    def __init__(self, executable=None, logger=None, timeout=None,
                 oned_as='row', temp_dir=None, convert_to_float=True):
        """Start Octave and set up the session.
        """
        self._oned_as = oned_as
        self._executable = executable

        self.timeout = timeout
        if logger is not None:
            self.logger = logger
        else:
            self.logger = get_log()
        self._engine = None
        self.temp_dir = temp_dir or tempfile.mkdtemp()
        self._convert_to_float = convert_to_float
        self._user_classes = dict()
        self.restart()

    @property
    def convert_to_float(self):
        return self._convert_to_float

    @convert_to_float.setter
    def convert_to_float(self, value):
        self._writer.convert_to_float = value
        self._convert_to_float = value

    def __enter__(self):
        """Return octave object, restart session if necessary"""
        if not self._engine:
            self.restart()
        return self

    def __exit__(self, type, value, traceback):
        """Close session"""
        self.exit()

    def exit(self):
        """Quits this octave session and removes temp files
        """
        if self._engine:
            self._engine.close()
        self._engine = None

    def push(self, name, var, verbose=True, timeout=None):
        """
        Put a variable or variables into the Octave session.

        Parameters
        ----------
        name : str or list
            Name of the variable(s).
        var : object or list
            The value(s) to pass.
        timeout : float
            Time to wait for response from Octave (per character).

        Examples
        --------
        >>> from oct2py import octave
        >>> y = [1, 2]
        >>> octave.push('y', y)
        >>> octave.pull('y')
        array([[1, 2]])
        >>> octave.push(['x', 'y'], ['spam', [1, 2, 3, 4]])
        >>> octave.pull(['x', 'y'])  # doctest: +SKIP
        [u'spam', array([[1, 2, 3, 4]])]

        Notes
        -----
        Integer type arguments will be converted to floating point
        unless `convert_to_float=False`.

        """
        if isinstance(name, (str, unicode)):
            name = [name]
            var = [var]

        for (n, v) in zip(name, var):
            self.feval('assignin', 'base', n, v, nout=0, verbose=verbose,
                       timeout=timeout)

    def pull(self, var, verbose=True, timeout=None):
        """
        Retrieve a value or values from the Octave session.

        Parameters
        ----------
        var : str or list
            Name of the variable(s) to retrieve.
        timeout : float
            Time to wait for response from Octave (per character).

        Returns
        -------
        out : object
            Object returned by Octave.

        Raises:
          Oct2PyError
            If the variable does not exist in the Octave session.

        Examples:
          >>> from oct2py import octave
          >>> y = [1, 2]
          >>> octave.push('y', y)
          >>> octave.pull('y')
          array([[1, 2]])
          >>> octave.push(['x', 'y'], ['spam', [1, 2, 3, 4]])
          >>> octave.pull(['x', 'y'])  # doctest: +SKIP
          [u'spam', array([[1, 2, 3, 4]])]

        """
        if isinstance(var, (str, unicode)):
            var = [var]
        outputs = []
        for name in var:
            exist = self._exist(name)
            isobject = self._isobject(name, exist)
            if exist == 1 and not isobject:
                outputs.append(self.feval('evalin', 'base', name,
                                          timeout=timeout, verbose=verbose))
            else:
                outputs.append(self.get_pointer(name, timeout=timeout))

        if len(outputs) == 1:
            return outputs[0]
        return outputs

    def get_pointer(self, name, timeout=None):
        exist = self._exist(name)
        isobject = self._isobject(name, exist)

        if exist == 1 and isobject:
            class_name = self.eval('class(%s);' % name)
            cls = self._get_user_class(class_name)
            return cls.from_name(name)

        elif exist == 1:
            return _make_variable_ptr_instance(self, name)

        elif isobject:
            return self._get_user_class(name)

        elif exist in [2, 3, 5]:
            return _make_function_ptr_instance(self, name)

        raise ValueError('Unknown type for object "%s"' % name)

    def extract_figures(self, plot_dir=None):
        """Save the figures to disk and extract the image objects.

        Parameters
        ----------
        plot_dir: str, optional
            The plot directory that was used in the call to "eval()".

        Notes
        -----
        This assumes that the figures were created with the specified
        `plot_dir`, e.g. `oc.plot([1,2,3], plot_dir='/tmp/foo').

        Returns
        -------
        out: list
            The IPython Image or SVG objects for the figures.
            These objects have a `.data` attribute with the raw image data,
            and can be used with the `display` function from `IPython` for
            rich display.
        """
        plot_dir = self._engine.make_figures(plot_dir)
        return self._engine.extract_figures(plot_dir)

    def set_plot_settings(self, width=None, height=None, format=None,
                          resolution=None, name=None, backend='inline'):
        """Handle plot settings for the session."""
        self.engine.plot_settings = dict(width=width, height=height,
            format=format, resolution=resolution, name=name, backend=backend)

    def feval(self, func_path, *func_args, nout=None, verbose=True,
              store_as='', timeout=None, **kwargs):
        """Run a function in Matlab and return the result.

        Parameters
        ----------
        func_path: str
            Name of function to run or a path to an m-file.
        func_args: object, optional
            Args to send to the function.
        nout: int, optional
            Desired number of return arguments.  If not given, the number
            of arguments will be inferred from the return value(s).
        verbose: int, optional
            If False, logs outputs at the DEBUG level instead of INFO.
        store_as: str, optional
            If given, saves the result to the given Octave variable name
            instead of returning it.
        timeout: float, optional
            The timeout in seconds for the call.
        kwargs:
            Keyword arguments are passed to Octave in the form [key, val] so
            that matlab.plot(x, y, '--', LineWidth=2) would be translated into
            plot(x, y, '--', 'LineWidth', 2).

        Returns
        -------
        The Python value(s) returned by the Octave function call.
        """
        if nout is None:
            nout = get_nout() or 1

        msg = 'Ignoring deprecated `plot_*` kwargs, use `set_plot_settings`'
        for key in list(kwargs.keys()):
            if key.startswith('plot_'):
                warnings.warn(msg)
            del kwargs[key]

        func_args += tuple(item for pair in zip(kwargs.keys(), kwargs.values())
                           for item in pair)
        dname = os.path.dirname(func_path)
        fname = os.path.basename(func_path)
        func_name, ext = os.path.splitext(fname)
        if ext and not ext == '.m':
            raise TypeError('Need to give path to .m file')
        return self._feval(func_name, func_args, dname=dname, nout=nout,
                          timeout=timeout, verbose=verbose, store_as=store_as)

    def eval(self, cmds, verbose=True, timeout=None, **kwargs):
        """
        Evaluate an Octave command or commands.

        Parameters
        ----------
        cmds : str or list
            Commands(s) to pass to Octave.
        verbose : bool, optional
             Log Octave output at INFO level.  If False, log at DEBUG level.
        timeout : float, optional
            Time to wait for response from Octave (per line).
        **kwargs Deprecated keyword arguments.  Use `set_plot_settings` for
                 deprecated `plot_*` kwargs.

        Returns
        -------
        out : object
            Octave "ans" variable, or None.

        Raises
        ------
        Oct2PyError
            If the command(s) fail.

        """
        if isinstance(cmds, (str, unicode)):
            cmds = [cmds]

        msg = 'Ignoring deprecated `plot_*` kwargs, use `set_plot_settings`'
        for key in kwargs:
            if key.startswith('plot_'):
                warnings.warn(msg)

        # Handle deprecated `temp_dir` kwarg.
        prev_temp_dir = self.temp_dir
        self.temp_dir = kwargs.get('temp_dir', prev_temp_dir)

        if 'log' in kwargs:
            msg = 'Ignoring deprecated `log` kwarg, use logging config'
            warnings.warn(msg)

        ans = None
        for cmd in cmds:
            resp = self.feval('evalin', 'base', cmd, verbose=verbose,
                              nout=0, timeout=timeout)
            if resp:
                ans = resp

        self.temp_dir = prev_temp_dir

        # Handle deprecated `return_both` kwarg.
        msg = '`return_both` kwarg is deprecated, use logging config'
        if kwargs.get('return_both', False):
            warnings.warn(msg)
            return '', ans

        return ans

    def restart(self):
        """Restart an Octave session in a clean state
        """
        if self._engine:
            self._engine.close()

        executable = self._executable
        if executable:
            os.environ['OCTAVE_EXECUTABLE'] = executable
        if 'OCTAVE_EXECUTABLE' not in os.environ and 'OCTAVE' in os.environ:
            os.environ['OCTAVE_EXECUTABLE'] = os.environ['OCTAVE']

        self._engine = OctaveEngine(stdin_handler=input)

        # Add local Octave scripts.
        here = os.path.realpath(os.path.dirname(__file__))
        self._engine.eval('addpath("%s");' % here.replace(os.path.sep, '/'))

    def _feval(self, func_name, func_args, dname='', nout=0,
              timeout=None, verbose=True, store_as=''):
        """Run the given function with the given args.
        """

        # Set up our mat file paths.
        out_file = os.path.join(self.temp_dir, 'writer.mat')
        out_file = out_file.replace(os.path.sep, '/')
        in_file = os.path.join(self.temp_dir, 'reader.mat')
        in_file = in_file.replace(os.path.sep, '/')

        replacements = []
        func_args = list(func_args)
        for (i, value) in enumerate(func_args):
            if isinstance(value, OctavePtr):
                replacements.append(i + 1)
                func_args[i] = value._address

        # Save the request data to the output file.
        req = dict(func_name=func_name, func_args=func_args,
                   dname=dname, nout=nout, store_as=store_as,
                   replacement_indices=replacements)

        write_file(req, out_file, oned_as=self._oned_as,
                   convert_to_float=self.convert_to_float)

        # Set up the engine and evaluate the `_pyeval()` function.
        engine = self._engine
        if not verbose:
            engine.stream_handler = self.logger.debug
        else:
            engine.stream_handler = self.logger.info
        engine.eval('_pyeval("%s", "%s");' % (out_file, in_file),
                    timeout=timeout)

        # Read in the output.
        resp = read_file(in_file, self)
        if resp['error']:
            self.logger.debug(resp['error'])
            raise Oct2PyError(resp['error']['message'])

        result = resp['result']
        if not str(result):
            result = None
        return result

    def _get_doc(self, name):
        """
        Get the documentation of an Octave procedure or object.

        Parameters
        ----------
        name : str
            Function name to search for.

        Returns
        -------
        out : str
          Documentation string.

        Raises
        ------
        Oct2PyError
           If the procedure or object function has a syntax error.

        """
        doc = 'No documentation for %s' % name

        try:
            doc = self.feval('help', name)
        except Oct2PyError as e:
            if 'syntax error' in str(e).lower():
                raise(e)
            doc = self.feval('type', name)
            if isinstance(doc, list):
                doc = doc[0]
            doc = '\n'.join(doc.splitlines()[:3])

        default = self.feval.__doc__
        default = '        ' + default[default.find('func_args:'):]
        default = '\n'.join([line[8:] for line in default.splitlines()])

        doc = '\n' + doc + '\n\nParameters\n----------\n' + default

        # convert to ascii for pydoc
        try:
            doc = doc.encode('ascii', 'replace').decode('ascii')
        except UnicodeDecodeError as e:
            self.logger.debug(e)

        return doc

    def _exist(self, name):
        """Test whether a name exists and return the name code.

        Raises an error when the name does not exist.
        """
        cmd = 'exist("%s")' % name
        resp = self._engine.eval(cmd, silent=True).strip()
        exist = int(resp.split()[-1])
        if exist == 0:
            raise ValueError('Value "%s" does not exist' % name)
        return exist

    def _isobject(self, name, exist):
        """Test whether the name is an object."""
        if exist in [2, 5]:
            return False
        cmd = 'isobject(%s)' % name
        resp = self._engine.eval(cmd, silent=True).strip()
        return resp == 'ans =  1'

    def _get_user_class(self, name):
        """Get or create a user class of the given type."""
        if name in self._user_classes:
            return self._user_classes[name]
        self._user_classes[name] = _make_user_class(self, name)

    def __getattr__(self, attr):
        """Automatically creates a wapper to an Octave function or object.

        Adapted from the mlabwrap project.
        """
        # needed for help(Oct2Py())
        if attr.startswith('__'):
            return super(Oct2Py, self).__getattr__(attr)

        # close_ -> close
        if attr[-1] == "_":
            name = attr[:-1]
        else:
            name = attr

        # Make sure the name exists.
        exist = self._exist(name)

        if exist not in [2, 3, 5, 103]:
            msg = 'Name "%s" is not a valid callable, use `pull` for variables'
            raise Oct2PyError(msg % name)

        # Check for user defined class.
        if self._isobject(name, exist):
            obj = self._get_user_class(name)
        else:
            obj = _make_function_ptr_instance(self, name)

        # !!! attr, *not* name, because we might have python keyword name!
        setattr(self, attr, obj)

        return obj
<<<<<<< HEAD


class _Session(object):

    """Low-level session Octave session interaction.
    """

    def __init__(self, executable, logger=None):
        if executable:
            os.environ['OCTAVE_EXECUTABLE'] = executable
        if 'OCTAVE_EXECUTABLE' not in os.environ and 'OCTAVE' in os.environ:
            os.environ['OCTAVE_EXECUTABLE'] = os.environ['OCTAVE']
        self.engine = OctaveEngine(stdin_handler=self._handle_stdin)
        self.proc = self.engine.repl.child
        self.logger = logger or get_log()
        self._lines = []
        atexit.register(self.close)

    def evaluate(self, cmds, logger=None, out_file='', log=True,
                 timeout=None):
        """Perform the low-level interaction with an Octave Session
        """
        self.logger = logger or self.logger
        engine = self.engine
        self._lines = []

        if not engine:
            raise Oct2PyError('Session Closed, try a restart()')

        if logger and log:
            engine.stream_handler = self._log_line
        else:
            engine.stream_handler = self._lines.append

        engine.eval('clear("ans", "_", "a__");', timeout=timeout)

        for cmd in cmds:
            if cmd:
                try:
                    engine.eval(cmd, timeout=timeout)
                except EOF:
                    self.close()
                    raise Oct2PyError('Session is closed')
        resp = '\n'.join(self._lines).rstrip()

        if 'parse error:' in resp:
            raise Oct2PyError('Syntax Error:\n%s' % resp)

        if 'error:' in resp:
            if len(cmds) == 5:
                main_line = cmds[2].strip()
            else:
                main_line = '\n'.join(cmds)
            msg = ('Oct2Py tried to run:\n"""\n{0}\n"""\n'
                   'Octave returned:\n{1}'
                   .format(cmds[0], resp))
            raise Oct2PyError(msg)

        if out_file:
            save_ans = """
            if exist("ans") == 1,
                _ = ans;
            end,
            if exist("ans") == 1,
                if exist("a__") == 0,
                    save -v6 -mat-binary %(out_file)s _;
                end,
            end;""" % locals()
            engine.eval(save_ans.strip().replace('\n', ''),
                        timeout=timeout)

        return resp

    def handle_plot_settings(self, plot_dir=None, plot_name='plot',
            plot_format='svg', plot_width=None, plot_height=None,
            plot_res=None):
        if not self.engine:
            return
        settings = dict(backend='inline' if plot_dir else 'gnuplot',
                        format=plot_format,
                        name=plot_name,
                        width=plot_width,
                        height=plot_height,
                        resolution=plot_res)
        self.engine.plot_settings = settings

    def extract_figures(self, plot_dir):
        if not self.engine:
            return
        return self.engine.extract_figures(plot_dir)

    def make_figures(self, plot_dir=None):
        if not self.engine:
            return
        return self.engine.make_figures(plot_dir)

    def interrupt(self):
        if not self.engine:
            return
        self.proc.kill(signal.SIGINT)

    def close(self):
        """Cleanly close an Octave session
        """
        if not self.engine:
            return
        proc = self.proc
        try:
            proc.sendline('\nexit')
        except Exception as e:  # pragma: no cover
            self.logger.debug(e)

        try:
            proc.kill(signal.SIGTERM)
            time.sleep(0.1)
            proc.kill(signal.SIGKILL)
        except Exception as e:  # pragma: no cover
            self.logger.debug(e)

        self.proc = None
        self.engine = None

    def _log_line(self, line):
        self._lines.append(line)
        self.logger.debug(line)

    def _handle_stdin(self, line):
        """Handle a stdin request from the session."""
        return input(line.replace(STDIN_PROMPT, ''))

    def __del__(self):
        try:
            self.close()
        except:
            pass
