# -*- coding: utf-8 -*-
"""XTGeo well module"""

from __future__ import print_function, absolute_import

import sys
import os.path
from copy import deepcopy

import numpy as np
import pandas as pd

import xtgeo.common.constants as const
import xtgeo.cxtgeo.cxtgeo as _cxtgeo
from xtgeo.common import XTGeoDialog
from xtgeo.well import _wellmarkers
from xtgeo.well import _well_io
from xtgeo.well import _well_roxapi
from xtgeo.well import _well_oper
from xtgeo.xyz import Polygons

xtg = XTGeoDialog()
logger = xtg.functionlogger(__name__)

# need to call the C function...
_cxtgeo.xtg_verbose_file('NONE')
XTGDEBUG = xtg.syslevel
# pylint: disable=too-many-public-methods


# =============================================================================
# METHODS as wrappers to class init + import


def well_from_file(wfile, fformat='rms_ascii', mdlogname=None,
                   zonelogname=None, strict=True):
    """Make an instance of a Well directly from file import.

    Args:
        mfile (str): Name of file
        fformat (str): See :meth:`Well.from_file`
        mdlogname (str): See :meth:`Well.from_file`
        zonelogname (str): See :meth:`Well.from_file`
        strict (bool): See :meth:`Well.from_file`

    Example::

        import xtgeo
        mywell = xtgeo.well_from_file('somewell.xxx')
    """

    obj = Well()

    obj.from_file(wfile, fformat=fformat, mdlogname=mdlogname,
                  zonelogname=zonelogname, strict=strict)

    return obj


def well_from_roxar(project, name, trajectory='Drilled trajectory',
                    logrun='log', lognames=None, inclmd=False,
                    inclsurvey=False):

    """This makes an instance of a RegularSurface directly from roxar input.

    For arguments, see :meth:`Well.from_roxar`.

    Example::

        # inside RMS:
        import xtgeo
        mysurf = xtgeo.surface_from_roxar(project, 'TopEtive', 'DepthSurface')

    """

    obj = Well()

    obj.from_roxar(project, name, trajectory=trajectory, logrun=logrun,
                   lognames=lognames, inclmd=inclmd, inclsurvey=inclsurvey)

    return obj


# =============================================================================
# CLASS

class Well(object):  # pylint: disable=useless-object-inheritance
    """Class for a well in the XTGeo framework.

    The well logs are stored as Pandas dataframe, which make manipulation
    easy and fast.

    The well trajectory are here represented as logs, and XYZ have magic names:
    X_UTME, Y_UTMN, Z_TVDSS, which are the three first Pandas columns.

    Other geometry logs has also 'semi-magic' names:

    M_MDEPTH or Q_MDEPTH: Measured depth, either real/true (M_) or
    quasi computed/estimated (Q_). The Quasi may be incorrect for
    all uses, but sufficient for some computations.

    Similar for M_INCL, Q_INCL, M_AZI, Q_ASI.

    The dataframe itself is a Pandas dataframe, and all values (yes,
    discrete also!) are stored as float64
    format, and undefined values are Nan. Integers are stored as Float due
    to the lacking support for 'Integer Nan' (currently lacking in Pandas,
    but may come in later Pandas versions).

    Note there is a method that can return a dataframe (copy) with Integer
    and Float columns, see :meth:`get_filled_dataframe`.

    The instance can be made either from file or (todo!) by spesification::

        >>> well1 = Well('somefilename')  # assume RMS ascii well
        >>> well2 = Well('somefilename', fformat='rms_ascii')
        >>> well3 = xtgeo.wells_from_file('somefilename')

    For arguments, see method under :meth:`from_file`.

    """

    UNDEF = const.UNDEF
    UNDEF_LIMIT = const.UNDEF_LIMIT
    UNDEF_INT = const.UNDEF_INT
    UNDEF_INT_LIMIT = const.UNDEF_INT_LIMIT

    def __init__(self, *args, **kwargs):

        # instance attributes
        self._wlogtype = dict()  # dictionary of log types, 'DISC' or 'CONT'
        self._wlogrecord = dict()  # code record for 'DISC' logs
        self._rkb = None  # well RKB height
        self._xpos = None  # well head X pos
        self._ypos = None  # well head Y pos
        self._wname = None  # well name
        self._df = None  # pandas dataframe with all log values
        # MD (MDEPTH) and ZONELOG are two essential logs; keep track of names!
        self._mdlogname = None
        self._zonelogname = None

        if args:
            # make instance from file import
            wfile = args[0]
            fformat = kwargs.get('fformat', 'rms_ascii')
            mdlogname = kwargs.get('mdlogname', None)
            zonelogname = kwargs.get('zonelogname', None)
            strict = kwargs.get('strict', True)
            self.from_file(wfile, fformat=fformat, mdlogname=mdlogname,
                           zonelogname=zonelogname, strict=strict)

        else:
            # dummy
            self._xx = kwargs.get('xx', 0.0)

            # # make instance by kw spesification ... todo
            # raise RuntimeWarning('Cannot initialize a Well object without '
            #                      'import at the current stage.')

        logger.debug('Ran __init__ method for RegularSurface object')

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def rkb(self):
        """ Returns RKB height for the well (read only)."""
        return self._rkb

    @property
    def xpos(self):
        """ Returns well header X position (read only)."""
        return self._xpos

    @property
    def ypos(self):
        """ Returns well header Y position (read only)."""
        return self._ypos

    @property
    def wellname(self):
        """ Returns well name (read only)."""
        return self._wname

    name = wellname

    @property
    def mdlogname(self):
        """ Returns name of MD log, if any (None if not) (read only)."""
        return self._mdlogname

    @property
    def zonelogname(self):
        """ Returns or sets name of zone log, return None if missing."""
        return self._zonelogname

    @zonelogname.setter
    def zonelogname(self, zname):
        self._zonelogname = zname

    @property
    def xwellname(self):
        """Returns well name on a file syntax safe form (/ and space replaced
        with _).
        """
        xname = self._wname
        xname = xname.replace('/', '_')
        xname = xname.replace(' ', '_')
        return xname

    @property
    def shortwellname(self):
        """Returns well name on a short name form where blockname and spaces
        are removed (read only).

        This should cope with both North Sea style and Haltenbanken style.

        E.g.: '31/2-G-5 AH' -> 'G-5AH', '6472_11-F-23_AH_T2' -> 'F-23AHT2'

        """
        newname = []
        first1 = False
        first2 = False
        for letter in self.wellname:
            if first1 and first2:
                newname.append(letter)
                continue
            if letter == '_' or letter == '/':
                first1 = True
                continue
            if first1 and letter == '-':
                first2 = True
                continue

        xname = ''.join(newname)
        xname = xname.replace('_', '')
        xname = xname.replace(' ', '')
        return xname

    @property
    def truewellname(self):
        """Returns well name on the assummed form aka '31/2-E-4 AH2'."""
        xname = self.xwellname
        if '/' not in xname:
            xname = xname.replace('_', '/', 1)
            xname = xname.replace('_', ' ')
        return xname

    @property
    def dataframe(self):
        """Returns or set the Pandas dataframe object for all logs."""
        return self._df

    @dataframe.setter
    def dataframe(self, dfr):
        self._df = dfr.copy()

    @property
    def nrow(self):
        """Returns the Pandas dataframe object number of rows"""
        return len(self._df.index)

    @property
    def ncol(self):
        """Returns the Pandas dataframe object number of columns"""
        return len(self._df.columns)

    @property
    def nlogs(self):
        """Returns the Pandas dataframe object number of columns"""
        return len(self._df.columns) - 3

    @property
    def lognames_all(self):
        """Returns the Pandas dataframe column names as list (including
        mandatory X_UTME Y_UTMN Z_TVDSS)."""
        return list(self._df)

    @property
    def lognames(self):
        """Returns the Pandas dataframe column as list (excluding
        mandatory X_UTME Y_UTMN Z_TVDSS)"""
        return list(self._df)[3:]

    # =========================================================================
    # Methods
    # =========================================================================

    def from_file(self, wfile, fformat='rms_ascii',
                  mdlogname=None, zonelogname=None, strict=True):
        """Import well from file.

        Args:
            wfile (str): Name of file
            fformat (str): File format, rms_ascii (rms well) is
                currently supported and default format.
            mdlogname (str): Name of measured depth log, if any
            zonelogname (str): Name of zonation log, if any
            strict (bool): If True, then import will fail if
                zonelogname or mdlogname are asked for but not present
                in wells.

        Returns:
            Object instance (optionally)

        Example:
            Here the from_file method is used to initiate the object
            directly::

            >>> mywell = Well('31_2-6.w')
        """

        if os.path.isfile(wfile):
            pass
        else:
            logger.critical('Not OK file')
            raise os.error

        if (fformat is None or fformat == 'rms_ascii'):
            _well_io.import_rms_ascii(self, wfile, mdlogname=mdlogname,
                                      zonelogname=zonelogname,
                                      strict=strict)
        else:
            logger.error('Invalid file format')

        return self

    def to_file(self, wfile, fformat='rms_ascii'):
        """
        Export well to file

        Args:
            wfile (str): Name of file
            fformat (str): File format

        Example::

            >>> x = Well()

        """
        if fformat is None or fformat == 'rms_ascii':
            _well_io.export_rms_ascii(self, wfile)

        elif fformat == 'hdf5':
            with pd.HDFStore(wfile, 'a', complevel=9, complib='zlib') as store:
                logger.info('export to HDF5 %s', wfile)
                store[self._wname] = self._df
                meta = dict()
                meta['name'] = self._wname
                store.get_storer(self._wname).attrs['metadata'] = meta

    def from_roxar(self, project, wname, trajectory='Drilled trajectory',
                   logrun='log', lognames=None, inclmd=False,
                   inclsurvey=False):
        """Import (retrieve) well from roxar project.

        Note this method works only when inside RMS, or when RMS license is
        activated.

        Args:
            project (str): Magic string 'project' or file path to project
            wname (str): Name of well, as shown in RMS.
            trajectory (str): Name of trajectory in RMS
            logrun (str): Name of logrun in RMS
            lognames (list): List of lognames to import
            inclmd (bool): Include MDEPTH as log M_MEPTH from RMS
            inclsurvey (bool): Include M_AZI and M_INCL from RMS
        """

        _well_roxapi.import_well_roxapi(self, project, wname,
                                        trajectory=trajectory,
                                        logrun=logrun, lognames=lognames,
                                        inclmd=inclmd, inclsurvey=inclsurvey)

    def copy(self):
        """Copy a Well instance to a new unique Well instance."""

        new = Well()
        new._wlogtype = deepcopy(self._wlogtype)
        new._wlogrecord = deepcopy(self._wlogrecord)
        new._rkb = self._rkb
        new._xpos = self._xpos = None
        new._ypos = self._ypos
        new._wname = self._wname
        if self._df is None:
            new._df = None
        else:
            new._df = self._df.copy()
        new._mdlogname = self._mdlogname
        new._zonelogname = self._zonelogname

        return new

    def get_logtype(self, lname):
        """Returns the type of a give log (e.g. DISC). None if not exists."""
        if lname in self._wlogtype:
            return self._wlogtype[lname]

        return None

    def get_logrecord(self, lname):
        """Returns the record (dict) of a give log. None if not exists"""

        if lname in self._wlogtype:
            return self._wlogrecord[lname]

        return None

    def set_logrecord(self, lname, newdict):
        """Sets the record (dict) of a given discrete log"""

        if lname in self._df.columns:
            self._wlogrecord[lname] = newdict
        else:
            raise ValueError('Cannot set records ... (unknown log name)')

    def get_logrecord_codename(self, lname, key):
        """Returns the name entry of a log record, for a given key

        Example::

            # get the name for zonelog entry no 4:
            zname = well.get_logrecord_codename('ZONELOG', 4)
        """

        zlogdict = self.get_logrecord(lname)
        if key in zlogdict:
            return zlogdict[key]

        return None

    def get_carray(self, lname):
        """Returns the C array pointer (via SWIG) for a given log.

        Type conversion is double if float64, int32 if DISC log.
        Returns None of log does not exist.
        """
        if lname in self._df:
            np_array = self._df[lname].values
        else:
            return None

        if self.get_logtype(lname) == 'DISC':
            carr = self._convert_np_carr_int(np_array)
        else:
            carr = self._convert_np_carr_double(np_array)

        return carr

    def get_filled_dataframe(self):
        """Fill the Nan's in the dataframe with real UNDEF values.

        This module returns a copy of the dataframe in the object; it
        does not change the instance.

        Returns:
            A pandas dataframe where Nan er replaces with high values.

        """

        lnames = self.lognames

        newdf = self._df.copy()

        # make a dictionary of datatypes
        dtype = {'X_UTME': 'float64', 'Y_UTMN': 'float64',
                 'Z_TVDSS': 'float64'}

        dfill = {'X_UTME': Well.UNDEF, 'Y_UTMN': Well.UNDEF,
                 'Z_TVDSS': Well.UNDEF}

        for lname in lnames:
            if self.get_logtype(lname) == 'DISC':
                dtype[lname] = 'int32'
                dfill[lname] = Well.UNDEF_INT
            else:
                dtype[lname] = 'float64'
                dfill[lname] = Well.UNDEF

        # now first fill Nan's (because int cannot be converted if Nan)
        newdf.fillna(dfill, inplace=True)

        # now cast to dtype
        newdf.astype(dtype, inplace=True)

        return newdf

    def create_relative_hlen(self):
        """Make a relative length of a well, as a log.

        The first well og entry defines zero, then the horizontal length
        is computed relative to that by simple geometric methods.
        """

        # extract numpies from XYZ trajectory logs
        ptr_xv = self.get_carray('X_UTME')
        ptr_yv = self.get_carray('Y_UTMN')
        ptr_zv = self.get_carray('Z_TVDSS')

        # get number of rows in pandas
        nlen = self.nrow

        ptr_hlen = _cxtgeo.new_doublearray(nlen)

        ier = _cxtgeo.pol_geometrics(nlen, ptr_xv, ptr_yv, ptr_zv, ptr_hlen,
                                     XTGDEBUG)

        if ier != 0:
            sys.exit(-9)

        dnumpy = self._convert_carr_double_np(ptr_hlen)
        self._df['R_HLEN'] = pd.Series(dnumpy, index=self._df.index)

        # delete tmp pointers
        _cxtgeo.delete_doublearray(ptr_xv)
        _cxtgeo.delete_doublearray(ptr_yv)
        _cxtgeo.delete_doublearray(ptr_zv)
        _cxtgeo.delete_doublearray(ptr_hlen)

    def geometrics(self):
        """Compute some well geometrical arrays MD and INCL, as logs.

        These are kind of quasi measurements hence the logs will named
        with a Q in front as Q_MDEPTH and Q_INCL.

        These logs will be added to the dataframe. If the mdlogname
        attribute does not exist in advance, it will be set to 'Q_MDEPTH'.
        """

        # extract numpies from XYZ trajetory logs
        ptr_xv = self.get_carray('X_UTME')
        ptr_yv = self.get_carray('Y_UTMN')
        ptr_zv = self.get_carray('Z_TVDSS')

        # get number of rows in pandas
        nlen = self.nrow

        ptr_md = _cxtgeo.new_doublearray(nlen)
        ptr_incl = _cxtgeo.new_doublearray(nlen)

        ier = _cxtgeo.well_geometrics(nlen, ptr_xv, ptr_yv, ptr_zv, ptr_md,
                                      ptr_incl, 0, XTGDEBUG)

        if ier != 0:
            sys.exit(-9)

        dnumpy = self._convert_carr_double_np(ptr_md)
        self._df['Q_MDEPTH'] = pd.Series(dnumpy, index=self._df.index)

        dnumpy = self._convert_carr_double_np(ptr_incl)
        self._df['Q_INCL'] = pd.Series(dnumpy, index=self._df.index)

        if not self._mdlogname:
            self._mdlogname = 'Q_MDEPTH'

        # delete tmp pointers
        _cxtgeo.delete_doublearray(ptr_xv)
        _cxtgeo.delete_doublearray(ptr_yv)
        _cxtgeo.delete_doublearray(ptr_zv)
        _cxtgeo.delete_doublearray(ptr_md)
        _cxtgeo.delete_doublearray(ptr_incl)

    def resample(self, interval=4, keeplast=True):
        """Resample by sampling every N'th element (coarsen only).

        Args:
            interval (int): Sampling interval.
            keeplast (bool): If True, the last element from the original
                dataframe is kept, to avoid that the well is shortened.
        """

        dfr = self._df[::interval]

        if keeplast:
            dfr.append(self._df.iloc[-1])

        self._df = dfr.reset_index(drop=True)

    def rescale(self, delta=0.15):
        """Rescale (refine or coarse) a well by sampling a delta along the
        trajectory, in MD.

        Args:
            delta (float): Step length
        """
        _well_oper.rescale(self, delta=delta)

    def get_fence_polyline(self, sampling=20, extend=2, tvdmin=None,
                           asnumpy=True):
        """
        Return a fence polyline as a numpy array or a Polygons object.

        Args:
            sampling (float): Sampling interval (input)
            extend (int): Number if sampling to extend; e.g. 2 * 20
            tvdmin (float): Minimum TVD starting point.
            as_numpy (bool): If True, a numpy array, otherwise a Polygons
                object with 5 columns where the 2 last are HLEN and POLY_ID
                and the POLY_ID will be set to 0.

        Returns:
            A numpy array of shape (NLEN, 4) in F order,
            Or a Polygons object with 5 columns
            If not possible return False
        """

        # pylint: disable=too-many-locals

        dfr = self._df

        if tvdmin is not None:
            self._df = dfr[dfr['Z_TVDSS'] > tvdmin]

        if len(self._df) < 2:
            xtg.warn('Well does not enough points in interval, outside range?')
            return False

        ptr_xv = self.get_carray('X_UTME')
        ptr_yv = self.get_carray('Y_UTMN')
        ptr_zv = self.get_carray('Z_TVDSS')

        nbuf = 1000000
        ptr_xov = _cxtgeo.new_doublearray(nbuf)
        ptr_yov = _cxtgeo.new_doublearray(nbuf)
        ptr_zov = _cxtgeo.new_doublearray(nbuf)
        ptr_hlv = _cxtgeo.new_doublearray(nbuf)

        ptr_nlen = _cxtgeo.new_intpointer()

        ier = _cxtgeo.pol_resampling(
            self.nrow, ptr_xv, ptr_yv, ptr_zv, sampling, sampling * extend,
            nbuf, ptr_nlen, ptr_xov, ptr_yov, ptr_zov, ptr_hlv,
            0, XTGDEBUG)

        if ier != 0:
            sys.exit(-2)

        nlen = _cxtgeo.intpointer_value(ptr_nlen)

        npxarr = self._convert_carr_double_np(ptr_xov, nlen=nlen)
        npyarr = self._convert_carr_double_np(ptr_yov, nlen=nlen)
        npzarr = self._convert_carr_double_np(ptr_zov, nlen=nlen)
        npharr = self._convert_carr_double_np(ptr_hlv, nlen=nlen)
        # npharr = npharr - sampling * extend ???

        if asnumpy is True:
            rval = np.concatenate((npxarr, npyarr, npzarr, npharr), axis=0)
            rval = np.reshape(rval, (nlen, 4), order='F')
        else:
            rval = Polygons()
            wna = self.xwellname
            idwell = [None] * extend + [wna] * (nlen - 2 * extend) + \
                     [None] * extend
            arr = np.vstack([npxarr, npyarr, npzarr, npharr,
                             np.zeros(nlen, dtype=np.int32)])
            col = ['X_UTME', 'Y_UTMN', 'Z_TVDSS', 'HLEN', 'ID']
            dfr = pd.DataFrame(arr.T, columns=col, dtype=np.float64)
            dfr = dfr.astype({'ID': int})
            dfr = dfr.assign(WELL=idwell)
            rval.dataframe = dfr
            rval.name = self.xwellname

        _cxtgeo.delete_doublearray(ptr_xov)
        _cxtgeo.delete_doublearray(ptr_yov)
        _cxtgeo.delete_doublearray(ptr_zov)
        _cxtgeo.delete_doublearray(ptr_hlv)

        return rval

    def report_zonation_holes(self, zonelogname=None, mdlogname=None,
                              threshold=5):
        """Reports if well has holes in zonation, less or equal to N samples.

        Zonation may have holes due to various reasons, and
        usually a few undef samples indicates that something is wrong.
        This method reports well and start interval of the "holes"

        Args:
            zonelogname (str): name of Zonelog to be applied
            threshold (int): Number of samples (max.) that defines a hole, e.g.
                5 means that undef samples in the range [1, 5] (including 5) is
                applied

        Returns:
            A Pandas dataframe as report. None if no list is made.
        """
        # pylint: disable=too-many-branches, too-many-statements

        if zonelogname is None:
            zonelogname = self._zonelogname

        if mdlogname is None:
            mdlogname = self._mdlogname

        logger.info('MDLOGNAME is %s', mdlogname)

        wellreport = []

        if zonelogname in self._df:
            zlog = self._df[zonelogname].values.copy()
        else:
            logger.warning('Cannot get zonelog')
            xtg.warn('Cannot get zonelog {} for {}'
                     .format(zonelogname, self.wellname))
            return None

        if mdlogname in self._df:
            mdlog = self._df[mdlogname].values
        else:
            logger.warning('Cannot get mdlog')
            xtg.warn('Cannot get mdlog {} for {}'
                     .format(mdlogname, self.wellname))
            return None

        xvv = self._df['X_UTME'].values
        yvv = self._df['Y_UTMN'].values
        zvv = self._df['Z_TVDSS'].values
        zlog[np.isnan(zlog)] = Well.UNDEF_INT

        ncv = 0
        first = True
        hole = False
        for ind, zone in np.ndenumerate(zlog):
            ino = ind[0]
            if zone > Well.UNDEF_INT_LIMIT and first:
                continue

            if zone < Well.UNDEF_INT_LIMIT and first:
                first = False
                continue

            if zone > Well.UNDEF_INT_LIMIT:
                ncv += 1
                hole = True

            if zone > Well.UNDEF_INT_LIMIT and ncv > threshold:
                logger.info('Restart first (bigger hole)')
                hole = False
                first = True
                ncv = 0
                continue

            if hole and zone < Well.UNDEF_INT_LIMIT and ncv <= threshold:
                # here we have a hole that fits criteria
                if mdlog is not None:
                    entry = (ino, xvv[ino], yvv[ino], zvv[ino],
                             int(zone), self.xwellname, mdlog[ino])
                else:
                    entry = (ino, xvv[ino], yvv[ino], zvv[ino], int(zone),
                             self.xwellname)

                wellreport.append(entry)

                # restart count
                hole = False
                ncv = 0

            if hole and zone < Well.UNDEF_INT_LIMIT and ncv > threshold:
                hole = False
                ncv = 0

        if not wellreport:  # ie length is 0
            return None

        if mdlog is not None:
            clm = ['INDEX', 'X_UTME', 'Y_UTMN', 'Z_TVDSS',
                   'Zone', 'Well', 'MD']
        else:
            clm = ['INDEX', 'X_UTME', 'Y_UTMN', 'Z_TVDSS', 'Zone', 'Well']

        return pd.DataFrame(wellreport, columns=clm)

    def get_zonation_points(self, tops=True, incl_limit=80, top_prefix='Top',
                            zonelist=None, use_undef=False):

        """Extract zonation points from Zonelog and make a marker list.

        Currently it is either 'Tops' or 'Zone' (thicknesses); default
        is tops (i.e. tops=True).

        Args:
            tops (bool): If True then compute tops, else (thickness) points.
            incl_limit (float): If given, and usezone is True, the max
                angle of inclination to be  used as input to zonation points.
            top_prefix (str): As well logs usually have isochore (zone) name,
                this prefix could be Top, e.g. 'SO43' --> 'TopSO43'
            zonelist (list of int): Zones to use
            use_undef (bool): If True, then transition from UNDEF is also
                used.


        Returns:
            A pandas dataframe (ready for the xyz/Points class), None
            if a zonelog is missing
        """

        zlist = []
        # get the relevant logs:

        self.geometrics()

        # as zlog is float64; need to convert to int array with high
        # number as undef
        if self.zonelogname is not None:
            zlog = self._df[self.zonelogname].values
            zlog[np.isnan(zlog)] = Well.UNDEF_INT
            zlog = np.rint(zlog).astype(int)
        else:
            return None

        xvv = self._df['X_UTME'].values
        yvv = self._df['Y_UTMN'].values
        zvv = self._df['Z_TVDSS'].values
        incl = self._df['Q_INCL'].values
        mdv = self._df['Q_MDEPTH'].values

        if self.mdlogname is not None:
            mdv = self._df[self.mdlogname].values

        if zonelist is None:
            # need to declare as list; otherwise Py3 will get dict.keys
            zonelist = list(self.get_logrecord(self.zonelogname).keys())

        logger.info('Find values for %s', zonelist)

        ztops, ztopnames, zisos, zisonames = (
            _wellmarkers.extract_ztops(self, zonelist, xvv, yvv, zvv, zlog,
                                       mdv, incl, tops=tops,
                                       incl_limit=incl_limit,
                                       prefix=top_prefix, use_undef=use_undef))

        if tops:
            zlist = ztops
        else:
            zlist = zisos

        logger.debug(zlist)

        if tops:
            dfr = pd.DataFrame(zlist, columns=ztopnames)
        else:
            dfr = pd.DataFrame(zlist, columns=zisonames)

        logger.debug(dfr)

        return dfr

    def get_zone_interval(self, zonevalue, resample=1, extralogs=None):

        """Extract the X Y Z ID line (polyline) segment for a given
        zonevalue.

        Args:
            zonevalue (int): The zone value to extract
            resample (int): If given, resample every N'th sample to make
                polylines smaller in terms of bit and bytes.
                1 = No resampling.
            extralogs (list of str): List of extra log names to include


        Returns:
            A pandas dataframe X Y Z ID (ready for the xyz/Polygon class),
            None if a zonelog is missing or actual zone does dot
            exist in the well.
        """

        if resample < 1 or not isinstance(resample, int):
            raise KeyError('Key resample of wrong type (must be int >= 1)')

        dff = self.get_filled_dataframe()

        # the technical solution here is to make a tmp column which
        # will add one number for each time the actual segment is repeated,
        # not straightforward... (thanks to H. Berland for tip)

        dff['ztmp'] = dff[self.zonelogname]
        dff['ztmp'] = (dff[self.zonelogname] != zonevalue).astype(int)

        dff['ztmp'] = (dff.ztmp != dff.ztmp.shift()).cumsum()

        dff = dff[dff[self.zonelogname] == zonevalue]

        m1v = dff['ztmp'].min()
        m2v = dff['ztmp'].max()
        if np.isnan(m1v):
            logger.debug('Returns (no data)')
            return None

        df2 = dff.copy()

        dflist = []
        for mvv in range(m1v, m2v + 1):
            dff9 = df2.copy()
            dff9 = df2[df2['ztmp'] == mvv]
            if dff9.index.shape[0] > 0:
                dflist.append(dff9)

        dxlist = []

        useloglist = ['X_UTME', 'Y_UTMN', 'Z_TVDSS', 'POLY_ID']
        if extralogs is not None:
            useloglist.extend(extralogs)

        # pylint: disable=consider-using-enumerate
        for ivv in range(len(dflist)):
            dxf = dflist[ivv]
            dxf = dxf.rename(columns={'ztmp': 'POLY_ID'})
            cols = [xxx for xxx in dxf.columns
                    if xxx not in useloglist]

            dxf = dxf.drop(cols, axis=1)

            # now resample every N'th
            if resample > 1:
                dxf = pd.concat([dxf.iloc[::resample, :], dxf.tail(1)])

            dxlist.append(dxf)

        dff = pd.concat(dxlist)
        dff.reset_index(inplace=True, drop=True)

        logger.debug('Dataframe from well:\n%s', dff)
        return dff

    def get_fraction_per_zone(self, dlogname, dcodes, zonelist=None,
                              incl_limit=80, count_limit=3, zonelogname=None):

        """Get fraction of a discrete parameter, e.g. a facies, per zone.

        It can be constrained by an inclination.

        Args:
            dlogname (str): Name of discrete log, e.g. 'FACIES'
            dnames (list of int): Codes of facies to report for
            zonelist (list of int): Zones to use
            incl_limit (float): Inclination limit for well path.
            count_limit (int): Minimum number of counts required per segment
                for valid calculations
            zonelogname (str). If None, the Well().zonelogname attribute is
                applied

        Returns:
            A pandas dataframe (ready for the xyz/Points class), None
            if a zonelog is missing or list is zero length for any reason

        """

        dfr = _wellmarkers.get_fraction_per_zone(
            self, dlogname, dcodes, zonelist=zonelist, incl_limit=incl_limit,
            count_limit=count_limit, zonelogname=zonelogname)

        return dfr

    # =========================================================================
    # PRIVATE METHODS
    # should not be applied outside the class
    # =========================================================================

    # -------------------------------------------------------------------------
    # Import/Export methods for various formats
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Special methods for nerds
    # -------------------------------------------------------------------------

    def _convert_np_carr_int(self, np_array):
        """Convert numpy 1D array to C array, assuming int type.

        The numpy is always a double (float64), so need to convert first
        """

        carr = _cxtgeo.new_intarray(self.nrow)

        np_array = np_array.astype(np.int32)

        _cxtgeo.swig_numpy_to_carr_i1d(np_array, carr)

        return carr

    def _convert_np_carr_double(self, np_array):
        """Convert numpy 1D array to C array, assuming double type."""
        carr = _cxtgeo.new_doublearray(self.nrow)

        _cxtgeo.swig_numpy_to_carr_1d(np_array, carr)

        return carr

    def _convert_carr_double_np(self, carray, nlen=None):
        """Convert a C array to numpy, assuming double type."""
        if nlen is None:
            nlen = len(self._df.index)

        nparray = _cxtgeo.swig_carr_to_numpy_1d(nlen, carray)

        return nparray
