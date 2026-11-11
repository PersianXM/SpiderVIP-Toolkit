"""SpiderVIP frequency update — refresh the receiver's TP list for all satellites.

Reference list: OpenPLi ``satellites.xml`` (rebuilt from LyngSat every day).
``core/`` is standard-library-only Python 3.9 so it can later run on the box.
UI: Console workspace ``/frequencies/`` (``webapp.create_app``).
"""
