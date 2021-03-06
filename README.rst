Oct2Py: Python to GNU Octave Bridge
===================================

.. image:: https://badge.fury.io/py/oct2py.png/
    :target: http://badge.fury.io/py/oct2py

.. image:: https://codecov.io/github/blink1073/oct2py/coverage.svg?branch=master
  :target: https://codecov.io/github/blink1073/oct2py?branch=master

.. image:: http://pepy.tech/badge/oct2py
   :target: http://pepy.tech/project/oct2py
   :alt: PyPi Download stats

Oct2Py allows you to seamlessly call M-files and Octave functions from Python.
It manages the Octave session for you, sharing data behind the scenes using
MAT files.  Usage is as simple as:

.. code-block:: python

    >>> oc = oct2py.Oct2Py()
    >>> x = oc.zeros(3,3)
    >>> print(x, x.dtype)
    [[ 0.  0.  0.]
     [ 0.  0.  0.]
     [ 0.  0.  0.]] float64
    ...

To run .m function, you need to explicitly add the path to .m file using:

.. code-block:: python

    >>> from oct2py import octave
    >>> # to add a folder use:
    >>> octave.addpath('/path/to/directory')
    >>> # to add folder with all subfolder in it use:
    >>> octave.addpath(octave.genpath('/path/to/directory'))
    >>> # to run the .m file :
    >>> octave.run('fileName.m')
    ...

To get the output of .m file after setting the path, use:

.. code-block:: python

    >>> x = np.array([[1, 2], [3, 4]], dtype=float)
    >>> #use nout='max_nout' to automatically choose max possible nout
    >>> out, oclass = octave.roundtrip(x,nout=2)
    >>> import pprint
    >>> pprint.pprint([x, x.dtype, out, oclass, out.dtype])
    [array([[1., 2.],
            [3., 4.]]),
        dtype('float64'),
        array([[1., 2.],
            [3., 4.]]),
        'double',
        dtype('<f8')]
    ...

If you want to run legacy m-files, do not have MATLAB®, and do not fully
trust a code translator, this is your library.

Features
--------

- Supports all Octave datatypes and most Python datatypes and Numpy dtypes.
- Provides OctaveMagic_ for IPython, including inline plotting in notebooks.
- Supports cell arrays and structs/struct arrays with arbitrary nesting.
- Supports sparse matrices.
- Builds methods on the fly linked to Octave commands (e.g. `zeros` above).
- Thread-safety: each Oct2Py object uses an independent Octave session.
- Can be used as a context manager.
- Supports Unicode characters.
- Supports logging of session commands.
- Optional timeout command parameter to prevent runaway Octave sessions.


.. _OctaveMagic: https://nbviewer.jupyter.org/github/blink1073/oct2py/blob/master/example/octavemagic_extension.ipynb?create=1


Installation
------------
You must have GNU Octave installed and in your ``PATH`` environment variable.
Alternatively, you can set an ``OCTAVE_EXECUTABLE`` or ``OCTAVE`` environment
variable that points to ``octave-cli`` executable itself.

You must have the Numpy and Scipy libraries for Python installed.
See the installation instructions_ for more details.

Once the dependencies have been installed, run:

.. code-block:: bash

    $ pip install oct2py

If using conda, it is available on conda-forge:

.. code-block:: bash

   $ conda install -c conda-forge oct2py

.. _instructions: http://blink1073.github.io/oct2py/source/installation.html


Documentation
-------------

Documentation is available online_.

For version information, see the Revision History_.

.. _online: https://oct2py.readthedocs.io/en/latest/

.. _History: https://github.com/blink1073/oct2py/blob/master/HISTORY.rst
